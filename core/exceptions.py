class ApplicationSpecificBaseError(Exception):
    """Base class for all application specific exceptions"""
    def __init__(self, exception_error_message_string, http_response_status_code_integer=500, additional_error_payload_dictionary=None):
        super().__init__()
        self.exception_error_message_string = exception_error_message_string
        self.http_response_status_code_integer = http_response_status_code_integer
        self.additional_error_payload_dictionary = additional_error_payload_dictionary

    def convert_error_to_dictionary_representation(self):
        return_value_dictionary_representation = dict(self.additional_error_payload_dictionary or ())
        return_value_dictionary_representation['error'] = self.exception_error_message_string
        return_value_dictionary_representation['success'] = False
        return return_value_dictionary_representation

class RequestPayloadValidationError(ApplicationSpecificBaseError):
    """Raised when request payload or parameters are invalid."""
    def __init__(self, exception_error_message_string="Invalid input", additional_error_payload_dictionary=None):
        super().__init__(exception_error_message_string, http_response_status_code_integer=400, additional_error_payload_dictionary=additional_error_payload_dictionary)

class RequestedResourceNotFoundError(ApplicationSpecificBaseError):
    """Raised when a requested resource is not found."""
    def __init__(self, exception_error_message_string="Resource not found", additional_error_payload_dictionary=None):
        super().__init__(exception_error_message_string, http_response_status_code_integer=404, additional_error_payload_dictionary=additional_error_payload_dictionary)

