import json
import logging
import os
import requests
import re
from datetime import datetime, timezone

from extensions import db
from models import AIAnalysis, Sphere

logger = logging.getLogger(__name__)


class AIService:
    """
    Handles LLM-backed country evaluation via a single structured request.
    All spheres and questions are sent in one call; the model fills the blanks
    and returns the same structure with scores and reasoning populated.
    """

    PROVIDER_CONFIG = {
        'groq': {
            'kind': 'openai_compatible',
            'url': 'https://api.groq.com/openai/v1/chat/completions',
            'model': 'llama-3.3-70b-versatile',
            'max_tokens': 32768,   # llama-3.3-70b-versatile supports up to 32k output
        },
        'openai': {
            'kind': 'openai_compatible',
            'url': 'https://api.openai.com/v1/chat/completions',
            'model': 'gpt-4o-mini',
            'max_tokens': 16384,   # gpt-4o-mini max output
        },
        'claude': {
            'kind': 'anthropic',
            'url': 'https://api.anthropic.com/v1/messages',
            'model': 'claude-3-5-sonnet-20241022',
            'anthropic_version': '2023-06-01',
            'max_tokens': 8192,
        },
        'gemini': {
            'kind': 'gemini',
            'url': 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            'model': 'gemini-2.0-flash-exp',
            'max_tokens': 8192,
        },
        'openrouter': {
            'kind': 'openai_compatible',
            'url': 'https://openrouter.ai/api/v1/chat/completions',
            'model': 'meta-llama/llama-3.3-70b-instruct',
            'max_tokens': 16384,
        },
    }

    def __init__(self):
        self.env_api_key = os.getenv('GROQ_API_KEY')
        if not self.env_api_key:
            logger.warning(
                "GROQ_API_KEY not set in environment. "
                "AI Evaluator will rely on user-saved API keys."
            )

    def evaluate_country(
        self,
        user_id,
        country_code,
        existing_analysis_id=None,
        additional_instructions=None,
        selected_key_id=None,
    ):
        """
        Evaluate a country in a single structured LLM request covering all spheres.
        selected_key_id: int key ID to use exclusively, 'system' for env key, None for auto fallback chain.
        """
        all_keys = self._resolve_all_api_keys(user_id, selected_key_id=selected_key_id)
        if not all_keys:
            raise RuntimeError("No API key available. Please configure an API key in the Setup page.")

        spheres = Sphere.get_all_ordered()
        if not spheres:
            raise RuntimeError("Institutional framework (spheres) not found in database.")

        if existing_analysis_id:
            analysis = AIAnalysis.get_by_id(existing_analysis_id)
            if not analysis:
                raise RuntimeError(f"AIAnalysis record {existing_analysis_id} disappeared.")
        else:
            analysis = AIAnalysis.get_by_country(country_code)
            if not analysis:
                analysis = AIAnalysis(country=country_code, status='in_progress').save()

        try:
            total_questions = sum(len(list(s.questions)) for s in spheres)
            self._update_status(analysis.id, 'in_progress', {
                'stage': f'Preparing evaluation request ({len(spheres)} spheres, {total_questions} questions)...',
                'progress': 5,
            })

            # Build the single structured request payload
            eval_payload = self._build_evaluation_payload(
                country_code, spheres, additional_instructions
            )

            self._update_status(analysis.id, 'in_progress', {
                'stage': 'Sending evaluation request to AI provider...',
                'progress': 15,
            })

            # Send with provider fallback
            ratings, comments, raw_sample = self._evaluate_with_fallback(
                all_keys, eval_payload, spheres
            )

            self._update_status(analysis.id, 'in_progress', {
                'stage': 'Computing sphere aggregates...',
                'progress': 90,
            })

            # Compute sphere-level aggregates (0–1 normalized)
            sphere_aggregates = {}
            for sphere in spheres:
                sphere_ratings = {
                    str(q.id): ratings[str(q.id)]
                    for q in sphere.questions
                    if str(q.id) in ratings
                }
                sphere_aggregates[sphere.name] = self._calculate_normalized_sphere_avg(sphere_ratings)

            analysis.mark_completed(
                scores=ratings,
                comments=comments,
                metadata={
                    'aggregates': sphere_aggregates,
                    'last_run_by_user_id': user_id,
                    'completion_timestamp': datetime.now(timezone.utc).isoformat(),
                    'provider_used': raw_sample.get('provider', 'Unknown'),
                    'model_used': raw_sample.get('model', ''),
                    'sample_raw_endpoint': raw_sample.get('endpoint', ''),
                    'sample_raw_request': raw_sample.get('request'),
                    'sample_raw_response': raw_sample.get('response'),
                }
            )
            return analysis.id

        except Exception as exc:
            logger.exception("AI evaluation critical failure for %s", country_code)
            analysis.mark_error(str(exc))
            raise

    # ── Core evaluation ─────────────────────────────────────────────────────

    def _evaluate_with_fallback(self, all_keys, eval_payload, spheres):
        """
        Tries each key in the fallback chain until one succeeds.
        Returns (ratings_dict, comments_dict, raw_sample_dict).
        """
        last_error = None
        for api_key, provider, config in all_keys:
            try:
                response, safe_request_body, endpoint_url = self._dispatch_request(
                    api_key, provider, config, eval_payload
                )
                response.raise_for_status()
                raw_resp_json = response.json()

                ratings, comments = self._parse_full_response(raw_resp_json, spheres, provider)

                raw_sample = {
                    'provider': provider,
                    'model': config.get('model', ''),
                    'endpoint': endpoint_url,
                    'request': safe_request_body,
                    'response': raw_resp_json,
                }
                return ratings, comments, raw_sample

            except Exception as e:
                last_error = e
                logger.warning(f"AI Provider {provider} failed: {str(e)[:120]}")
                continue

        raise RuntimeError(
            f"All AI providers failed. Last error: {last_error}"
        )

    # ── Prompt construction ──────────────────────────────────────────────────

    def _build_evaluation_payload(self, country, spheres, additional_instructions=None):
        """
        Builds the structured JSON object sent as the LLM input.

        Questions are keyed by their ID string. The model receives null slots for
        score and reasoning and must return the identical structure with those filled.

        Structure:
        {
          "context": { role, task, scoring_scale, output_requirements },
          "evaluation_target": "Country Name",
          "spheres": {
            "sphere_name": {
              "label": "Human Label",
              "questions": {
                "42": { "content": "...", "score": null, "reasoning": null },
                ...
              }
            },
            ...
          }
        }
        """
        payload = {
            "context": {
                "role": "Senior Institutional Analyst and Anti-Corruption Expert",
                "task": (
                    f"Evaluate the institutional legitimacy of '{country}' by scoring every "
                    "question in every sphere listed below."
                ),
                "scoring_scale": {
                    "type": "integer",
                    "1": "Extremely Weak / Highly Corrupt / Failed Institution",
                    "4": "Neutral / Average Performance",
                    "7": "Extremely Strong / Transparent / High Integrity"
                },
                "output_requirements": [
                    "For every question key, set 'score' to an integer between 1 and 7",
                    "For every question key, set 'reasoning' to a concise evidence-based string",
                    "Return the EXACT same JSON structure — same sphere keys, same question keys",
                    "Output valid JSON only — no markdown fences, no text outside the JSON"
                ]
            },
            "evaluation_target": country,
            "spheres": {}
        }

        if additional_instructions:
            payload["context"]["additional_instructions"] = additional_instructions

        for sphere in spheres:
            payload["spheres"][sphere.name] = {
                "label": sphere.label,
                "questions": {
                    str(q.id): {
                        "content": q.content,
                        "score": None,
                        "reasoning": None
                    }
                    for q in sphere.questions
                }
            }

        return payload

    # ── HTTP dispatch ────────────────────────────────────────────────────────

    def _dispatch_request(self, key, provider, config, eval_payload):
        """
        Structures the API call for each provider type.
        The eval_payload JSON is the user message content.
        Returns (response, safe_request_body, endpoint_url) — no credentials in safe_request_body.
        """
        kind = config['kind']
        headers = {"Content-Type": "application/json"}

        # Serialize the evaluation payload as the user content
        user_content = json.dumps(eval_payload, ensure_ascii=False)

        system_instruction = (
            "You are a professional institutional analyst. "
            "You will receive a JSON evaluation task. "
            "Fill in every null 'score' (integer 1-7) and 'reasoning' (string) field, "
            "then return the complete JSON with all fields populated. "
            "Output valid JSON only — no markdown, no commentary."
        )

        if kind == 'openai_compatible':
            headers["Authorization"] = f"Bearer {key}"
            payload = {
                "model": config['model'],
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.2,
                "max_tokens": config['max_tokens'],
                "response_format": {"type": "json_object"}
            }
            url = config['url']
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            return resp, payload, url

        elif kind == 'anthropic':
            headers["x-api-key"] = key
            headers["anthropic-version"] = config['anthropic_version']
            payload = {
                "model": config['model'],
                "max_tokens": config['max_tokens'],
                "system": system_instruction,
                "messages": [{"role": "user", "content": user_content}],
                "temperature": 0.2
            }
            url = config['url']
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            return resp, payload, url

        elif kind == 'gemini':
            url = config['url'].format(model=config['model'])
            payload = {
                "system_instruction": {"parts": [{"text": system_instruction}]},
                "contents": [{"parts": [{"text": user_content}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                    "maxOutputTokens": config['max_tokens'],
                }
            }
            resp = requests.post(f"{url}?key={key}", headers=headers, json=payload, timeout=120)
            return resp, payload, url

        raise ValueError(f"Unsupported provider kind: {kind}")

    # ── Response parsing ─────────────────────────────────────────────────────

    def _parse_full_response(self, data, spheres, provider):
        """
        Extracts scores and reasoning from the structured JSON response.

        Reads parsed['spheres'][sphere_name]['questions'][str(q_id)] for each question
        and builds flat dicts keyed by question ID string — matching AIAnalysis storage format.
        """
        try:
            # Extract raw text from the provider-specific envelope
            if provider in ['groq', 'openai', 'openrouter']:
                text = data['choices'][0]['message']['content']
            elif provider == 'claude':
                text = data['content'][0]['text']
            elif provider == 'gemini':
                text = data['candidates'][0]['content']['parts'][0]['text']
            else:
                raise ValueError(f"Parser not implemented for {provider}")

            text = text.strip()
            # Robust JSON extraction in case the model wraps output in markdown fences
            json_match = re.search(r'(\{.*\})', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)

            parsed = json.loads(text)
            spheres_data = parsed.get('spheres', {})

            ratings = {}
            comments = {}

            # Walk the canonical sphere/question list to ensure full coverage
            for sphere in spheres:
                sphere_resp = spheres_data.get(sphere.name, {})
                questions_resp = sphere_resp.get('questions', {})

                for q in sphere.questions:
                    qid = str(q.id)
                    item = questions_resp.get(qid, {})

                    raw_score = item.get('score')
                    try:
                        score = int(raw_score)
                        ratings[qid] = max(1, min(7, score))
                    except (ValueError, TypeError):
                        ratings[qid] = "NA"

                    reasoning = item.get('reasoning')
                    comments[qid] = reasoning if reasoning else "AI reasoning not provided."

            return ratings, comments

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"Failed to parse AI response from {provider}: {str(e)}")
            raise RuntimeError(f"Data corruption in AI response from {provider}")

    # ── Utilities ────────────────────────────────────────────────────────────

    def _update_status(self, aid, status, metadata):
        """Partial commit — updates metadata_json and status without touching scores."""
        analysis = AIAnalysis.get_by_id(aid)
        if analysis:
            analysis.status = status
            if not analysis.metadata_json:
                analysis.metadata_json = {}
            analysis.metadata_json.update(metadata)
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(analysis, "metadata_json")
            db.session.commit()

    def _calculate_normalized_sphere_avg(self, ratings):
        """Returns a normalized 0.0–1.0 score for a dict of {qid: score} ratings."""
        try:
            valid_vals = [int(v) for v in ratings.values() if str(v).isdigit()]
            if not valid_vals:
                return 0.0
            return round(sum(valid_vals) / (len(valid_vals) * 7), 3)
        except Exception:
            return 0.0

    def _resolve_all_api_keys(self, user_id, selected_key_id=None):
        """
        Builds the ordered key chain for provider fallback.
        selected_key_id: int → use only that key; 'system' → env key only; None → all active + env fallback.
        """
        from models.api_key_models import APIKey

        if selected_key_id == 'system':
            if self.env_api_key:
                return [(self.env_api_key, 'groq', self.PROVIDER_CONFIG['groq'])]
            return []

        user_keys = APIKey.get_active_user_keys(user_id)

        if selected_key_id:
            try:
                target_id = int(selected_key_id)
                selected = next((k for k in user_keys if k.id == target_id), None)
                if selected:
                    config = self.PROVIDER_CONFIG.get(selected.provider)
                    if config:
                        return [(selected.get_key(), selected.provider, config)]
            except (ValueError, TypeError):
                pass
            return []

        all_keys = []
        for uk in user_keys:
            config = self.PROVIDER_CONFIG.get(uk.provider)
            if config:
                all_keys.append((uk.get_key(), uk.provider, config))

        if self.env_api_key:
            all_keys.append((self.env_api_key, 'groq', self.PROVIDER_CONFIG['groq']))

        return all_keys
