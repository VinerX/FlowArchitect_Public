class Events:
    """
    Single source of truth for event names used across the project.
    Keep this file as a superset of all events referenced anywhere in code.
    """

    class Core:
        LOG = "core_log"
        ERROR = "core_error"
        # System / cross-component (legacy)
        GET_EVENT_LOOP = "get_event_loop"
        LOOP_READY = "loop_ready"
        RUN_IN_LOOP = "run_in_loop"
        SETTING_CHANGED = "setting_changed"

    class Etl:
        # новое (под Orchestrator/GUI)
        USER_QUERY = "etl.user_query"
        REQUEST_CONVERSION = "etl.request_conversion"

        # старое (можно оставить для совместимости)
        REQUEST_GENERATION = "etl_request_generation"
        PIM_GENERATED = "etl_pim_generated"
        PSM_CONVERTED = "etl_psm_converted"
        ERROR = "etl_error"

    class GUI:
        """Events intended for GUI controllers."""
        UPDATE_TOKEN_COUNT = "update_token_count"
        UPDATE_STATUS = "update_status"
        UPDATE_DEBUG_INFO = "update_debug_info"
        SHOW_MITA_THINKING = "show_mita_thinking"
        SHOW_MITA_ERROR = "show_mita_error"
        HIDE_MITA_STATUS = "hide_mita_status"
        PULSE_MITA_ERROR = "pulse_mita_error"
        SHOW_LOADING_POPUP = "show_loading_popup"
        CLOSE_LOADING_POPUP = "close_loading_popup"
        CLEAR_USER_INPUT = "clear_user_input"
        CLEAR_USER_INPUT_UI = "clear_user_input_ui"
        PREPARE_STREAM_UI = "prepare_stream_ui"
        APPEND_STREAM_CHUNK_UI = "append_stream_chunk_ui"
        FINISH_STREAM_UI = "finish_stream_ui"
        CHECK_AND_INSTALL_FFMPEG = "check_and_install_ffmpeg"
        UPDATE_STATUS_COLORS = "update_status_colors"
        UPDATE_CHAT_UI = "update_chat_ui"
        INSERT_TEXT_TO_INPUT = "insert_text_to_input"
        CHECK_USER_ENTRY_EXISTS = "check_user_entry_exists"
        SWITCH_VOICEOVER_SETTINGS = "switch_voiceover_settings"
        SHOW_INFO_MESSAGE = "show_info_message"
        UPDATE_CHAT_FONT_SIZE = "update_chat_font_size"
        RELOAD_CHAT_HISTORY = "reload_chat_history"
        UPDATE_TOKEN_COUNT_UI = "update_token_count_ui"
        GET_GUI_WINDOW_ID = "get_gui_window_id"
        CHECK_TRITON_DEPENDENCIES = "check_triton_dependencies"
        SHOW_ERROR_MESSAGE = "show_error_message"
        UPDATE_LOCAL_VOICE_COMBOBOX = "update_local_voice_combobox"
        SHOW_EULA_DIALOG = "show_eula_dialog"
        SHOW_GUIDE = "show_guide"
        HIDE_GUIDE = "hide_guide"
        SHOW_WINDOW = "show_window"
        CLOSE_WINDOW = "close_window"
        CLOSE_ALL_WINDOWS = "close_all_windows"
        SET_SETTINGS_ICON_INDICATOR = "set_settings_icon_indicator"

        VOICEOVER_UI_READY = "voiceover_ui_ready"
        VOICEOVER_REFRESH = "voiceover_refresh"
        VOICEOVER_MODEL_SELECTED = "voiceover_model_selected"

    class Model:
        """Events for LLM/model/history orchestration."""
        LOAD_HISTORY = "load_history"
        GET_CHAT_HISTORY = "get_chat_history"
        LOAD_MORE_HISTORY = "load_more_history"
        SCHEDULE_G4F_UPDATE = "schedule_g4f_update"
        GET_CURRENT_CONTEXT_TOKENS = "get_current_context_tokens"
        CALCULATE_COST = "calculate_cost"
        RELOAD_PROMPTS_ASYNC = "reload_prompts_async"
        GET_DEBUG_INFO = "get_debug_info"
        ON_STARTED_RESPONSE_GENERATION = "on_started_response_generation"
        ON_SUCCESSFUL_RESPONSE = "on_successful_response"
        ON_FAILED_RESPONSE = "on_failed_response"
        ON_FAILED_RESPONSE_ATTEMPT = "on_failed_attempt_for_response"
        ADD_TEMPORARY_SYSTEM_INFO = "add_temporary_system_info"
        GENERATE_RESPONSE = "generate_response"
        GET_LLM_PROCESSING_STATUS = "get_llm_processing_status"
        GET_GAME_STATE = "get_game_state"
        PEEK_TEMPORARY_SYSTEM_INFOS = "peek_temporary_system_infos"
        TOKENS_REPORTED = "model_tokens_reported"

    class Editor:
        UPDATE_CODE = "editor_update_code"
        GET_CONTENT = "editor_get_content"

    class Chat:
        # new (Orchestrator-style)
        SEND_MESSAGE = "chat_send_message"
        NEW_MESSAGE = "chat_new_message"
        USER_MESSAGE_SAVED = "chat_user_message_saved"  # payload: {db_id, session_id}

        # legacy (used by existing controllers)
        CLEAR_CHAT = "clear_chat"
        ATTACH_IMAGES = "attach_images"
        STAGE_IMAGE = "stage_image"
        CLEAR_STAGED_IMAGES = "clear_staged_images"

    class Settings:
        # new
        SAVE = "settings_save"
        LOAD = "settings_load"
        SETTING_CHANGED = "setting_changed"

        # legacy
        SAVE_SETTING = "save_setting"
        GET_SETTING = "get_setting"
        LOAD_SETTINGS = "load_settings"
        GET_SETTINGS = "get_settings"
        GET_APP_VARS = "get_app_vars"

    class Audio:
        """Voiceover/audio pipeline events."""
        SELECT_VOICE_MODEL = "select_voice_model"
        INIT_VOICE_MODEL = "init_voice_model"
        CHECK_MODEL_INSTALLED = "check_model_installed"
        CHECK_MODEL_INITIALIZED = "check_model_initialized"
        CHANGE_VOICE_LANGUAGE = "change_voice_language"
        REFRESH_VOICE_MODULES = "refresh_voice_modules"
        DELETE_SOUND_FILES = "delete_sound_files"
        SET_WAITING_ANSWER = "set_waiting_answer"
        UPDATE_MODEL_LOADING_STATUS = "update_model_loading_status"
        FINISH_MODEL_LOADING = "finish_model_loading"
        CANCEL_MODEL_LOADING = "cancel_model_loading"
        GET_WAITING_ANSWER = "get_waiting_answer"
        VOICEOVER_REQUESTED = "voiceover_requested"
        OPEN_VOICE_MODEL_SETTINGS = "open_voice_model_settings"
        OPEN_VOICE_MODEL_SETTINGS_DIALOG = "open_voice_model_settings_dialog"
        SHOW_VC_REDIST_DIALOG = "show_vc_redist_dialog"
        SHOW_TRITON_DIALOG = "show_triton_dialog"
        REFRESH_TRITON_STATUS = "refresh_triton_status"
        GET_TRITON_STATUS = "get_triton_status"

        # LocalVoiceController
        LOCAL_SEND_VOICE_REQUEST = "local_send_voice_request"
        LOCAL_INSTALL_MODEL = "local_install_voice_model"
        LOCAL_UNINSTALL_MODEL = "local_uninstall_voice_model"
        GET_ALL_LOCAL_MODEL_CONFIGS = "get_all_local_model_configs"

    class Speech:
        """ASR/microphone events."""
        GET_MIC_STATUS = "get_mic_status"
        SET_MICROPHONE = "set_microphone"
        START_SPEECH_RECOGNITION = "start_speech_recognition"
        STOP_SPEECH_RECOGNITION = "stop_speech_recognition"
        UPDATE_SPEECH_SETTINGS = "update_speech_settings"
        GET_USER_INPUT = "get_user_input"
        GET_INSTANT_SEND_STATUS = "get_instant_send_status"
        SET_INSTANT_SEND_STATUS = "set_instant_send_status"
        SPEECH_TEXT_RECOGNIZED = "speech_text_recognized"
        GET_MICROPHONE_LIST = "get_microphone_list"
        REFRESH_MICROPHONE_LIST = "refresh_microphone_list"
        SET_GIGAAM_OPTIONS = "set_gigaam_options"
        RESTART_SPEECH_RECOGNITION = "restart_speech_recognition"

        INSTALL_ASR_MODEL = "install_asr_model"
        CHECK_ASR_MODEL_INSTALLED = "check_asr_model_installed"
        ASR_MODEL_INSTALL_STARTED = "asr_model_install_started"
        ASR_MODEL_INSTALL_PROGRESS = "asr_model_install_progress"
        ASR_MODEL_INSTALL_FINISHED = "asr_model_install_finished"
        ASR_MODEL_INSTALL_FAILED = "asr_model_install_failed"
        ASR_MODEL_INITIALIZED = "asr_model_initialized"

        GET_RECOGNIZER_SETTINGS_SCHEMA = "get_asr_settings_schema"
        GET_RECOGNIZER_SETTINGS = "get_asr_settings"
        SET_RECOGNIZER_OPTION = "set_recognizer_option"
        APPLY_RECOGNIZER_SETTINGS = "apply_recognizer_settings"
        ASR_MODEL_INIT_STARTED = "asr_model_init_started"
        GET_ASR_MODELS_GLOSSARY = "get_asr_models_glossary"
        GET_ASR_ENGINES_LIST = "get_asr_engines_list"

    class Capture:
        """Screen/camera capture events."""
        CAPTURE_SCREEN = "capture_screen"
        GET_CAMERA_FRAMES = "get_camera_frames"
        GET_SCREEN_CAPTURE_STATUS = "get_screen_capture_status"
        GET_CAMERA_CAPTURE_STATUS = "get_camera_capture_status"
        STOP_SCREEN_CAPTURE = "stop_screen_capture"
        STOP_CAMERA_CAPTURE = "stop_camera_capture"
        START_SCREEN_CAPTURE = "start_screen_capture"
        START_CAMERA_CAPTURE = "start_camera_capture"
        START_IMAGE_REQUEST_TIMER = "start_image_request_timer"
        STOP_IMAGE_REQUEST_TIMER = "stop_image_request_timer"
        UPDATE_SCREEN_CAPTURE_EXCLUSION = "update_screen_capture_exclusion"
        CAPTURE_SETTINGS_LOADED = "capture_settings_loaded"
        SEND_PERIODIC_IMAGE_REQUEST = "send_periodic_image_request"
        UPDATE_LAST_IMAGE_REQUEST_TIME = "update_last_image_request_time"

    class Server:
        """TCP server / game client events."""
        GET_GAME_CONNECTION = "get_connection_status"
        STOP_SERVER = "stop_server"
        SET_GAME_CONNECTION = "update_game_connection"
        SET_GAME_DATA = "set_game_data"
        SET_DIALOG_ACTIVE = "set_dialog_active"
        SET_ID_SOUND = "set_id_sound"
        GET_SERVER_DATA = "get_server_data"
        RESET_SERVER_DATA = "reset_server_data"
        GET_CHAT_SERVER = "get_chat_server"
        SET_PATCH_TO_SOUND_FILE = "set_patch_to_sound_file"
        SEND_TASK_UPDATE = "send_task_update"
        LOAD_SERVER_SETTINGS = "load_server_settings"
        ECHO_CHAT_MESSAGE_REQUESTED = "echo_chat_message_requested"
        BROADCAST_ASR_TEXT = "broadcast_asr_text"

    class Telegram:
        """Telegram integration events."""
        GET_SILERO_STATUS = "get_silero_status"
        REQUEST_TG_CODE = "request_tg_code"
        REQUEST_TG_PASSWORD = "request_tg_password"
        SET_SOUND_FILE_DATA = "set_sound_file_data"
        SET_SILERO_CONNECTED = "set_silero_connected"
        PROMPT_FOR_TG_CODE = "prompt_for_tg_code"
        PROMPT_FOR_TG_PASSWORD = "prompt_for_tg_password"
        TELEGRAM_SEND_VOICE_REQUEST = "telegram_send_voice_request"
        START_SILERO = "telegram_start_silero"
        STOP_SILERO = "telegram_stop_silero"

    class VoiceModel:
        """Local voice models management (UI) events."""
        GET_MODEL_DATA = "get_voice_model_data"
        GET_INSTALLED_MODELS = "get_installed_models"
        GET_DEPENDENCIES_STATUS = "get_dependencies_status"
        GET_DEFAULT_DESCRIPTION = "get_default_description"
        GET_MODEL_DESCRIPTION = "get_model_description"
        GET_SETTING_DESCRIPTION = "get_setting_description"
        GET_SECTION_VALUES = "get_section_values"
        CHECK_GPU_RTX30_40 = "check_gpu_rtx30_40"
        INSTALL_MODEL = "install_voice_model"
        UNINSTALL_MODEL = "uninstall_voice_model"
        SAVE_SETTINGS = "save_voice_model_settings"
        CLOSE_DIALOG = "close_voice_model_dialog"
        OPEN_DOC = "open_voice_model_doc"
        UPDATE_DESCRIPTION = "update_voice_model_description"
        CLEAR_DESCRIPTION = "clear_voice_model_description"
        MODEL_INSTALL_STARTED = "voice_model_install_started"
        MODEL_INSTALL_FINISHED = "voice_model_install_finished"
        MODEL_UNINSTALL_STARTED = "voice_model_uninstall_started"
        MODEL_UNINSTALL_FINISHED = "voice_model_uninstall_finished"
        REFRESH_MODEL_PANELS = "refresh_voice_model_panels"
        REFRESH_SETTINGS_DISPLAY = "refresh_voice_settings_display"

    class Task:
        """Task manager events."""
        CREATE_TASK = "create_task"
        UPDATE_TASK_STATUS = "update_task_status"
        GET_TASK = "get_task"
        TASK_CREATED = "task_created"
        TASK_STATUS_CHANGED = "task_status_changed"
        NOTIFY_TASK_UPDATE = "notify_task_update"

    class ApiPresets:
        GET_PRESET_LIST = "get_preset_list"
        GET_PRESET_FULL = "get_preset_full"
        SAVE_CUSTOM_PRESET = "save_custom_preset"
        DELETE_CUSTOM_PRESET = "delete_custom_preset"
        EXPORT_PRESET = "export_preset"
        IMPORT_PRESET = "import_preset"
        TEST_CONNECTION = "test_connection"
        TEST_RESULT = "test_result"
        TEST_FAILED = "test_failed"
        SET_GEMINI_CASE = "set_gemini_case"
        PRESET_SAVED = "preset_saved"
        PRESET_DELETED = "preset_deleted"
        PRESET_IMPORTED = "preset_imported"
        SAVE_PRESET_STATE = "save_preset_state"
        LOAD_PRESET_STATE = "load_preset_state"
        GET_CURRENT_PRESET_ID = "get_current_preset_id"
        SET_CURRENT_PRESET_ID = "set_current_preset_id"
        UPDATE_PRESET_MODELS = "update_preset_models"
        SAVE_PRESETS_ORDER = "save_presets_order"

    class Protocols:
        GET_PROTOCOL_LIST = "get_protocol_list"
        GET_PROTOCOL_FULL = "get_protocol_full"
        GET_TRANSFORM_LIST = "get_transform_list"
        BUILD_HTTP_REQUEST = "build_protocol_http_request"

    class Prompt:
        """LLM prompt building."""
        BUILD_PROMPT = "build_prompt"

    class History:
        """Chat history handling."""
        PREPARE_FOR_PROMPT = "prepare_history_for_prompt"
        SAVE_AFTER_RESPONSE = "save_history_after_response"

    class RAG:
        GET_EMBEDDING = "rag_get_embedding"
        GET_EMBEDDINGS = "rag_get_embeddings"

    class Install:
        """Unified installer manager events."""
        RUN_WITH_UI = "run_install_with_ui"
        RUN_HEADLESS = "run_install_headless"
        TASK_STARTED = "install_task_started"
        TASK_PROGRESS = "install_task_progress"
        TASK_LOG = "install_task_log"
        TASK_FINISHED = "install_task_finished"
        TASK_FAILED = "install_task_failed"
        RUN_BLOCKING = "run_install_blocking"

    class NiFi:
        """NiFi integration events."""
        IMPORT_FLOW     = "nifi_import_flow"
        TEST_CONNECTION = "nifi_test_connection"
        IMPORT_RESULT   = "nifi_import_result"   # payload: {ok, pg_id, validation_errors}

    class Character:
        GET_ALL = "character_get_all"
        GET = "character_get"
        GET_CURRENT_PROFILE = "character_get_current_profile"
        GET_CURRENT_NAME = "character_get_current_name"
        SET_CURRENT = "character_set_current"
        RELOAD_DATA = "character_reload_data"
        RELOAD_PROMPTS = "character_reload_prompts"
        CLEAR_HISTORY = "character_clear_history"
        CLEAR_ALL_HISTORIES = "character_clear_all_histories"
        CURRENT_CHANGED = "character_current_changed"

    class Session:
        """DB session lifecycle events."""
        CREATED = "session.created"       # payload: {session_id, name, mode}
        LOADED = "session.loaded"         # payload: {session_id, name}
        NAME_UPDATED = "session.name_updated"  # payload: {session_id, name}
        LIST_UPDATED = "session.list_updated"  # payload: {} – history panel should refresh
        LLM_LOGGED = "session.llm_logged" # payload: {session_id, provider, model, duration_ms, purpose}
