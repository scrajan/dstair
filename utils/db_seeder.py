import os
import json
import uuid
import logging
from werkzeug.security import generate_password_hash

from extensions import db
from models import User, Sphere, Question, Tool, ToolCriteria, Comment, Country
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')

def load_json_data(filename):
    """
    Load JSON data from a file in the `data/` directory.

    Args:
        filename (str): Name of the JSON file to load.

    Returns:
        list or dict: Parsed JSON data or an empty list if the file is not found or decoding fails.
    """
    filepath = os.path.join(DATA_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"File not found: {filepath}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON {filename}: {e}")
        return []

def seed_countries():
    logger.info("Seeding Countries...")
    countries = load_json_data('countries.json')
    if not countries: return

    for country_name in countries:
        existing = Country.query.filter_by(code=country_name).first()
        if not existing:
            country = Country(
                code=country_name,
                name=country_name
            )
            db.session.add(country)
    db.session.flush()

def seed_users():
    logger.info("Seeding Users...")
    data = load_json_data('users.json')
    if not data: return

    for u_data in data:
        username = u_data['username']
        password = u_data['password']
        role = u_data['role']
        name = u_data.get('name')

        user = User.query.filter_by(user_account_unique_username_string=username).first()
        if not user:
            new_user = User(
                user_account_unique_username_string=username,
                user_account_full_name_string=name,
                user_account_hashed_password_string=generate_password_hash(password, method='scrypt'),
                user_account_authorization_role_identifier_string=role,
                boolean_flag_indicating_if_user_profile_has_been_completed=True
            )
            db.session.add(new_user)
            logger.info(f"Created user: {username}")
        else:
            changed = False
            if user.user_account_authorization_role_identifier_string != role:
                user.user_account_authorization_role_identifier_string = role
                changed = True
            if name and user.user_account_full_name_string != name:
                user.user_account_full_name_string = name
                changed = True
            
            # Ensure seeded users have their profile marked as completed
            if not user.boolean_flag_indicating_if_user_profile_has_been_completed:
                user.boolean_flag_indicating_if_user_profile_has_been_completed = True
                changed = True
                
            if changed:
                logger.info(f"Updated attributes for user: {username}")

def seed_spheres():
    logger.info("Seeding Spheres...")
    data = load_json_data('spheres.json')
    if not data: return
    
    for s_data in data:
        name = s_data['name']
        existing = Sphere.query.filter_by(name=name).first()
        if not existing:
            sphere = Sphere(
                name=name,
                label=s_data['label'],
                order=s_data['order']
            )
            db.session.add(sphere)
            logger.info(f"Created Sphere: {name}")
        else:
            existing.label = s_data['label']
            existing.order = s_data['order']

def seed_questionnaire():
    """
    Seeds the Questionnaire & Legacy Comments into the database from a JSON file.

    The JSON file should contain a list of spheres, each containing a list of questions.
    Each question should have the following attributes:
        - id: integer
        - text: string
        - type_header: string (RULE, POLICY, etc.)
        - importance_header: string (HIGH, MEDIUM, etc.)
        - comments: list of legacy comments (each with user and comment attributes)
        
    For each question, the function will create a new Question object and add it to the database.
    If the question already exists, it will update its attributes.
    For each legacy comment, the function will create a new Comment object and add it to the database.
    If the comment already exists, it will not be duplicated.
    
    The function will log information for each created/updated question and comment.
    """

    logger.info("Seeding Questionnaire & Legacy Comments...")
    data = load_json_data('questionnaire.json')
    if not data: return

    for s_data in data:
        sphere_name = s_data['sphere']
        sphere = Sphere.query.filter_by(name=sphere_name).first()
        
        if not sphere:
            logger.warning(f"Sphere {sphere_name} not found in database. Skipping questions.")
            continue
        
        for q_data in s_data['questions']:
            q_id = q_data['id']
            q_content = q_data['text']
            
            existing_q = Question.query.filter_by(sphere_id=sphere.id, content=q_content).first()
            
            importance_str = q_data.get('importance_header', '')
            importance = 1
            if 'HIGH' in importance_str: importance = 3
            elif 'MEDIUM' in importance_str: importance = 2
            
            raw_type = q_data.get('type_header', '').strip()
            type_str = raw_type if raw_type else 'RULE'
            
            legacy_comments = q_data.get('comments', [])

            if not existing_q:
                q = Question(
                    sphere_id=sphere.id,
                    order=q_id,
                    content=q_content,
                    scale_min_label=q_data.get('rating_min'),
                    scale_max_label=q_data.get('rating_max'),
                    type=type_str,
                    importance=importance,
                    help_info=q_data.get('info_link')
                )
                db.session.add(q)
                db.session.flush() # flush to get the question ID
                logger.debug(f"Created Question {q_id} in {sphere_name}")
                
                # Create relational comments for the new question
                for c_data in legacy_comments:
                    comment = Comment(
                        id=str(uuid.uuid4()),
                        question_id=q.id,
                        user_display=c_data.get('user', 'Legacy User'),
                        text=c_data.get('comment', '')
                    )
                    db.session.add(comment)
            else:
                existing_q.importance = importance
                existing_q.type = type_str
                existing_q.help_info = q_data.get('info_link')
                # Comments are not duplicated — already in the DB from initial seed.

def seed_tools():
    logger.info("Seeding Tools...")
    data = load_json_data('tools.json')
    if not data: return

    for t_data in data:
        title = t_data['title']
        existing_tool = Tool.query.filter_by(title=title).first()
        
        if not existing_tool:
            tool = Tool(
                id=t_data['id'],
                title=title,
                description=t_data['description'],
                content=t_data.get('content', '')
            )
            db.session.add(tool)
            logger.info(f"Created Tool: {title}")
        else:
            existing_tool.description = t_data['description']
            existing_tool.content = t_data.get('content', '')

def seed_criteria():
    logger.info("Seeding Criteria...")
    data = load_json_data('criteria.json')
    if not data: return

    if ToolCriteria.query.count() == 0:
        for c_data in data:
            tc = ToolCriteria(
                tool_id=c_data['tool_id'],
                sphere_id=c_data['sphere_id'],
                min_score_threshold=float(c_data['min_score_threshold'])
            )
            db.session.add(tc)
        logger.info("Tool Criteria seeded.")
    else:
        logger.info("Tool Criteria already exists. Skipping.")

def seed_ai_analyses():
    logger.info("Seeding 200 Countries for AI Analysis...")
    from models.ai_analysis_models import AIAnalysis
    countries = load_json_data("countries.json")
    if not countries: return
    
    questionnaire = load_json_data("questionnaire.json")
    if not questionnaire: return
    
    # Build skeletons
    scores_skeleton = {}
    comments_skeleton = {}
    for sphere in questionnaire:
        for q in sphere.get("questions", []):
            scores_skeleton[str(q["id"])] = None
            comments_skeleton[str(q["id"])] = ""
    
    count = 0
    for country in countries:
        existing = AIAnalysis.query.filter_by(country=country).first()
        if not existing:
            ai_record = AIAnalysis(
                country=country,
                status='not_started',
                ai_comments_for_all_questions=comments_skeleton,
                ai_scores_for_all_questions=scores_skeleton,
                metadata_json={}
            )
            db.session.add(ai_record)
            count += 1
            
    if count > 0:
        logger.info(f"Seeded {count} new AIAnalysis records with JSON skeletons.")
    else:
        logger.info("AI Analysis records already seeded.")

def run_seeding():
    try:
        logger.info("Starting database seeding process...")
        seed_countries()
        seed_users()
        seed_spheres()
        seed_questionnaire()
        seed_tools()
        seed_criteria()
        seed_ai_analyses()
        db.session.commit()
        logger.info("Database seeding completed successfully.")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Seeding failed: {e}")
        import traceback
        traceback.print_exc()
