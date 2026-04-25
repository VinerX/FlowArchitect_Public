from __future__ import annotations

import json
import posixpath
from collections import defaultdict, deque
from typing import Any
from uuid import uuid4

from src.domain.interfaces import BaseAdapter
from src.domain.pim_model import DataProcessingElement, DataSink, DataSource, Flow, Link

Component = DataSource | DataProcessingElement | DataSink


# ---------------------------------------------------------------------------
# Bundle mapping: processor package prefix -> NAR artifact name
# Used to populate the required "bundle" field in NiFi 2.x flow JSON.
# ---------------------------------------------------------------------------

_BUNDLE_MAP: list[tuple[str, str]] = [
    ("org.apache.nifi.processors.kafka",        "nifi-kafka-nar"),
    ("org.apache.nifi.processors.aws",          "nifi-aws-nar"),
    ("org.apache.nifi.processors.gcp",          "nifi-gcp-nar"),
    ("org.apache.nifi.processors.azure",        "nifi-azure-nar"),
    ("org.apache.nifi.processors.mongodb",      "nifi-mongodb-nar"),
    ("org.apache.nifi.processors.elasticsearch","nifi-elasticsearch-restapi-nar"),
    ("org.apache.nifi.processors.mqtt",         "nifi-mqtt-nar"),
    ("org.apache.nifi.processors.amqp",         "nifi-amqp-nar"),
    ("org.apache.nifi.jms.processors",          "nifi-jms-processors-nar"),
    ("org.apache.nifi.processors.script",       "nifi-scripting-nar"),
    ("org.apache.nifi.processors.groovyx",      "nifi-groovyx-nar"),
    ("org.apache.nifi.processors.jolt",         "nifi-jolt-nar"),
    ("org.apache.nifi.processors.avro",         "nifi-avro-nar"),
    ("org.apache.nifi.processors.websocket",    "nifi-websocket-processors-nar"),
    ("org.apache.nifi.processors.hadoop",       "nifi-hadoop-nar"),
    ("org.apache.nifi.processors.email",        "nifi-email-nar"),
    ("org.apache.nifi.processors.slack",        "nifi-slack-nar"),
    ("org.apache.nifi.processors.attributes",   "nifi-update-attribute-nar"),
    # Standard must be last as it's the broadest match
    ("org.apache.nifi.processors.standard",     "nifi-standard-nar"),
]

_BUNDLE_GROUP = "org.apache.nifi"

# Bundle mapping for controller services
_SERVICE_BUNDLE_MAP: dict[str, str] = {
    "org.apache.nifi.dbcp.DBCPConnectionPool":               "nifi-dbcp-service-nar",
    "org.apache.nifi.dbcp.HikariCPConnectionPool":           "nifi-hikari-dbcp-service-nar",
    "org.apache.nifi.json.JsonTreeReader":                   "nifi-record-serialization-services-nar",
    "org.apache.nifi.json.JsonRecordSetWriter":              "nifi-record-serialization-services-nar",
    "org.apache.nifi.avro.AvroReader":                       "nifi-record-serialization-services-nar",
    "org.apache.nifi.avro.AvroRecordSetWriter":              "nifi-record-serialization-services-nar",
    "org.apache.nifi.csv.CSVReader":                         "nifi-record-serialization-services-nar",
    "org.apache.nifi.csv.CSVRecordSetWriter":                "nifi-record-serialization-services-nar",
    "org.apache.nifi.xml.XMLReader":                         "nifi-record-serialization-services-nar",
    "org.apache.nifi.xml.XMLRecordSetWriter":                "nifi-record-serialization-services-nar",
    "org.apache.nifi.lookup.SimpleCsvFileLookupService":     "nifi-lookup-services-nar",
    "org.apache.nifi.lookup.SimpleKeyValueLookupService":    "nifi-lookup-services-nar",
    "org.apache.nifi.ssl.StandardSSLContextService":         "nifi-ssl-context-service-nar",
    "org.apache.nifi.security.util.StandardKeyStoreService": "nifi-ssl-context-service-nar",
}


def _resolve_service_bundle(service_type: str, nifi_version: str) -> dict[str, str]:
    artifact = _SERVICE_BUNDLE_MAP.get(service_type, "nifi-standard-nar")
    return {"group": _BUNDLE_GROUP, "artifact": artifact, "version": nifi_version}


def _resolve_bundle(processor_type: str, nifi_version: str) -> dict[str, str]:
    for prefix, artifact in _BUNDLE_MAP:
        if processor_type.startswith(prefix):
            return {"group": _BUNDLE_GROUP, "artifact": artifact, "version": nifi_version}
    return {"group": _BUNDLE_GROUP, "artifact": "nifi-standard-nar", "version": nifi_version}


# ---------------------------------------------------------------------------
# Processor type mapping tables
# ---------------------------------------------------------------------------

# Source type keyword -> NiFi processor fully-qualified class name
_SOURCE_TYPE_MAP: list[tuple[list[str], str]] = [
    # Kafka
    (["kafka"], "org.apache.nifi.processors.kafka.pubsub.ConsumeKafka_2_6"),
    # Local filesystem
    (["file", "filesystem", "local", "directory"], "org.apache.nifi.processors.standard.GetFile"),
    # FTP / SFTP
    (["sftp"], "org.apache.nifi.processors.standard.GetSFTP"),
    (["ftp"], "org.apache.nifi.processors.standard.GetFTP"),
    # HTTP / REST
    (["http", "https", "rest", "api", "webhook"], "org.apache.nifi.processors.standard.InvokeHTTP"),
    (["listen_http", "listenhttp", "http_listener", "httplistener"],
     "org.apache.nifi.processors.standard.ListenHTTP"),
    # AWS
    (["s3", "aws_s3", "amazon_s3"], "org.apache.nifi.processors.aws.s3.FetchS3Object"),
    (["sqs", "aws_sqs", "amazon_sqs"], "org.apache.nifi.processors.aws.sqs.GetSQS"),
    (["kinesis"], "org.apache.nifi.processors.aws.kinesis.stream.ConsumeKinesisStream"),
    # GCP
    (["gcs", "google_cloud_storage", "gcp_storage"],
     "org.apache.nifi.processors.gcp.storage.FetchGCSObject"),
    (["pubsub", "gcp_pubsub", "google_pubsub"],
     "org.apache.nifi.processors.gcp.pubsub.ConsumeGCPubSub"),
    # Azure
    (["azure_blob", "azure_storage", "azureblob"],
     "org.apache.nifi.processors.azure.storage.FetchAzureBlobStorage_v12"),
    (["azure_event_hub", "eventhub", "azure_eventhub"],
     "org.apache.nifi.processors.azure.eventhub.ConsumeAzureEventHub"),
    # Databases (SQL) — QueryDatabaseTableRecord for table-based sources
    (["postgresql", "postgres", "mysql", "mariadb", "oracle", "sqlserver",
      "mssql", "database", "jdbc", "sql", "db", "sqlite", "h2"],
     "org.apache.nifi.processors.standard.QueryDatabaseTableRecord"),
    # MongoDB
    (["mongodb", "mongo"], "org.apache.nifi.processors.mongodb.GetMongo"),
    # Elasticsearch
    (["elasticsearch", "elastic", "opensearch"],
     "org.apache.nifi.processors.elasticsearch.SearchElasticsearch"),
    # Messaging
    (["mqtt"], "org.apache.nifi.processors.mqtt.ConsumeMQTT"),
    (["amqp", "rabbitmq", "rabbit"], "org.apache.nifi.processors.amqp.ConsumeAMQP"),
    (["jms", "activemq", "tibco"], "org.apache.nifi.jms.processors.ConsumeJMS"),
    # Network / Syslog
    (["syslog"], "org.apache.nifi.processors.standard.ListenSyslog"),
    (["tcp"], "org.apache.nifi.processors.standard.ListenTCP"),
    (["udp"], "org.apache.nifi.processors.standard.ListenUDP"),
    # WebSocket
    (["websocket", "ws"], "org.apache.nifi.processors.websocket.ListenWebSocket"),
    # HDFS
    (["hdfs", "hadoop"], "org.apache.nifi.processors.hadoop.GetHDFS"),
    # Email
    (["imap", "pop3", "email_in", "email_receive"],
     "org.apache.nifi.processors.email.ConsumeIMAP"),
]

# Sink type keyword -> NiFi processor
_SINK_TYPE_MAP: list[tuple[list[str], str]] = [
    # Kafka
    (["kafka"], "org.apache.nifi.processors.kafka.pubsub.PublishKafka_2_6"),
    # Local filesystem / structured file formats
    (["file", "filesystem", "local", "directory", "csv", "tsv", "json_file", "text"],
     "org.apache.nifi.processors.standard.PutFile"),
    # FTP / SFTP
    (["sftp"], "org.apache.nifi.processors.standard.PutSFTP"),
    (["ftp"], "org.apache.nifi.processors.standard.PutFTP"),
    # HTTP / REST
    (["http", "https", "rest", "api", "webhook"], "org.apache.nifi.processors.standard.InvokeHTTP"),
    # AWS
    (["s3", "aws_s3", "amazon_s3"], "org.apache.nifi.processors.aws.s3.PutS3Object"),
    (["sqs", "aws_sqs", "amazon_sqs"], "org.apache.nifi.processors.aws.sqs.PutSQS"),
    (["sns", "aws_sns", "amazon_sns"], "org.apache.nifi.processors.aws.sns.PutSNS"),
    (["kinesis"], "org.apache.nifi.processors.aws.kinesis.stream.PutKinesisStream"),
    (["lambda", "aws_lambda"], "org.apache.nifi.processors.aws.lambda.PutLambda"),
    (["dynamodb", "dynamo"], "org.apache.nifi.processors.aws.dynamodb.PutDynamoDB"),
    (["cloudwatch"], "org.apache.nifi.processors.aws.cloudwatch.PutCloudWatchMetric"),
    # GCP
    (["gcs", "google_cloud_storage", "gcp_storage"],
     "org.apache.nifi.processors.gcp.storage.PutGCSObject"),
    (["pubsub", "gcp_pubsub", "google_pubsub"],
     "org.apache.nifi.processors.gcp.pubsub.PublishGCPubSub"),
    # Azure
    (["azure_blob", "azure_storage", "azureblob"],
     "org.apache.nifi.processors.azure.storage.PutAzureBlobStorage_v12"),
    (["azure_event_hub", "eventhub", "azure_eventhub"],
     "org.apache.nifi.processors.azure.eventhub.PutAzureEventHub"),
    (["cosmosdb", "azure_cosmos", "cosmos"],
     "org.apache.nifi.processors.azure.cosmos.document.PutAzureCosmosDBRecord"),
    # Databases (SQL)
    (["postgresql", "postgres", "mysql", "mariadb", "oracle", "sqlserver",
      "mssql", "database", "jdbc", "sql", "db", "sqlite", "h2"],
     "org.apache.nifi.processors.standard.PutDatabaseRecord"),
    # MongoDB
    (["mongodb", "mongo"], "org.apache.nifi.processors.mongodb.PutMongoRecord"),
    # Elasticsearch
    (["elasticsearch", "elastic", "opensearch"],
     "org.apache.nifi.processors.elasticsearch.PutElasticsearchRecord"),
    # Messaging
    (["mqtt"], "org.apache.nifi.processors.mqtt.PublishMQTT"),
    (["amqp", "rabbitmq", "rabbit"], "org.apache.nifi.processors.amqp.PublishAMQP"),
    (["jms", "activemq", "tibco"], "org.apache.nifi.jms.processors.PublishJMS"),
    # Network / Syslog
    (["syslog"], "org.apache.nifi.processors.standard.PutSyslog"),
    (["tcp"], "org.apache.nifi.processors.standard.PutTCP"),
    (["udp"], "org.apache.nifi.processors.standard.PutUDP"),
    # WebSocket
    (["websocket", "ws"], "org.apache.nifi.processors.websocket.PutWebSocket"),
    # HDFS
    (["hdfs", "hadoop"], "org.apache.nifi.processors.hadoop.PutHDFS"),
    # Email
    (["smtp", "email", "email_out", "email_send", "mail"],
     "org.apache.nifi.processors.standard.PutEmail"),
    # Logging / Debug
    (["log", "debug", "console"], "org.apache.nifi.processors.standard.LogAttribute"),
    # Slack
    (["slack"], "org.apache.nifi.processors.slack.PutSlack"),
]

# Processing operation keyword -> NiFi processor
_OPERATION_MAP: list[tuple[list[str], str]] = [
    # Filtering / SQL-based record querying
    (["filter", "where", "select", "sql_query", "query_record"],
     "org.apache.nifi.processors.standard.QueryRecord"),
    # Routing
    (["route", "branch", "switch", "route_attribute", "routeonattribute"],
     "org.apache.nifi.processors.standard.RouteOnAttribute"),
    (["route_content", "routeoncontent", "content_route"],
     "org.apache.nifi.processors.standard.RouteOnContent"),
    (["route_text", "routetext"],
     "org.apache.nifi.processors.standard.RouteText"),
    # Record format conversion
    (["convert", "convert_record", "format_convert", "record_convert", "serialize",
      "deserialize"],
     "org.apache.nifi.processors.standard.ConvertRecord"),
    # JSON transformation
    (["jolt", "jolt_transform", "json_transform", "transform_json"],
     "org.apache.nifi.processors.jolt.JoltTransformJSON"),
    # JSON path extraction
    (["json_path", "jsonpath", "evaluate_json", "extract_json"],
     "org.apache.nifi.processors.standard.EvaluateJsonPath"),
    # XPath / XQuery
    (["xpath", "evaluate_xpath", "xml_path"],
     "org.apache.nifi.processors.standard.EvaluateXPath"),
    (["xquery", "evaluate_xquery"],
     "org.apache.nifi.processors.standard.EvaluateXQuery"),
    # Splitting
    (["split_json", "splitjson"], "org.apache.nifi.processors.standard.SplitJson"),
    (["split_xml", "splitxml"], "org.apache.nifi.processors.standard.SplitXml"),
    (["split_text", "splittext", "split_lines"],
     "org.apache.nifi.processors.standard.SplitText"),
    (["split_record", "splitrecord"],
     "org.apache.nifi.processors.standard.SplitRecord"),
    (["split_avro", "splitavro"],
     "org.apache.nifi.processors.avro.SplitAvro"),
    (["split"], "org.apache.nifi.processors.standard.SplitJson"),
    # Merging / Aggregation
    (["merge", "aggregate", "combine", "concat", "merge_content", "mergecontent"],
     "org.apache.nifi.processors.standard.MergeContent"),
    (["merge_record", "mergerecord"],
     "org.apache.nifi.processors.standard.MergeRecord"),
    # Text manipulation
    (["replace", "replace_text", "replacetext", "regex_replace", "substitute"],
     "org.apache.nifi.processors.standard.ReplaceText"),
    (["extract_text", "extracttext", "regex_extract"],
     "org.apache.nifi.processors.standard.ExtractText"),
    # Record operations
    (["update_record", "updaterecord", "modify_record", "enrich_record"],
     "org.apache.nifi.processors.standard.UpdateRecord"),
    (["partition", "partition_record", "partitionrecord", "group_by"],
     "org.apache.nifi.processors.standard.PartitionRecord"),
    (["validate", "validate_record", "validaterecord", "schema_validate"],
     "org.apache.nifi.processors.standard.ValidateRecord"),
    (["lookup", "lookup_record", "lookuprecord", "enrich", "join", "lookup_join"],
     "org.apache.nifi.processors.standard.LookupRecord"),
    # Compression
    (["compress", "gzip", "bzip2", "lzma", "snappy", "zstd", "deflate"],
     "org.apache.nifi.processors.standard.CompressContent"),
    (["decompress", "unzip", "gunzip", "extract_archive"],
     "org.apache.nifi.processors.standard.CompressContent"),
    (["unpack", "untar", "unzip_archive"],
     "org.apache.nifi.processors.standard.UnpackContent"),
    # Encryption
    (["encrypt", "decrypt", "cipher"],
     "org.apache.nifi.processors.standard.EncryptContent"),
    # Hashing
    (["hash", "checksum", "md5", "sha256", "sha1"],
     "org.apache.nifi.processors.standard.HashContent"),
    # Base64
    (["base64", "base64_encode", "base64_decode"],
     "org.apache.nifi.processors.standard.Base64EncodeContent"),
    # Attribute manipulation
    (["set_attribute", "update_attribute", "updateattribute", "attribute", "metadata",
      "add_attribute", "rename_attribute"],
     "org.apache.nifi.processors.attributes.UpdateAttribute"),
    (["attributes_to_json", "attributestojson"],
     "org.apache.nifi.processors.standard.AttributesToJSON"),
    # Scripting
    (["script", "python", "groovy", "javascript", "lua", "ruby", "clojure", "udf",
      "custom", "custom_logic", "execute_script"],
     "org.apache.nifi.processors.script.ExecuteScript"),
    (["groovy_script", "executegroovy"],
     "org.apache.nifi.processors.groovyx.ExecuteGroovyScript"),
    # System / external process
    (["execute_process", "command", "cmd", "shell", "process", "exec"],
     "org.apache.nifi.processors.standard.ExecuteProcess"),
    (["execute_stream", "stream_command", "pipe"],
     "org.apache.nifi.processors.standard.ExecuteStreamCommand"),
    # SQL on DB
    (["execute_sql", "executesql", "sql", "query_db", "run_sql"],
     "org.apache.nifi.processors.standard.ExecuteSQL"),
    (["put_sql", "putsql", "insert_sql", "write_sql"],
     "org.apache.nifi.processors.standard.PutSQL"),
    # HTTP call (as processing step)
    (["http_call", "api_call", "invoke_http", "invokehttp", "rest_call", "fetch_url",
      "http_request", "http"],
     "org.apache.nifi.processors.standard.InvokeHTTP"),
    # Flow control
    (["wait"], "org.apache.nifi.processors.standard.Wait"),
    (["notify", "signal"], "org.apache.nifi.processors.standard.Notify"),
    (["rate_limit", "throttle", "control_rate", "controlrate"],
     "org.apache.nifi.processors.standard.ControlRate"),
    (["deduplicate", "dedup", "detect_duplicate", "detectduplicate", "distinct"],
     "org.apache.nifi.processors.standard.DetectDuplicate"),
    # Content identification
    (["identify_mime", "detect_type", "mime_type", "content_type"],
     "org.apache.nifi.processors.standard.IdentifyMimeType"),
    # Generate (test/mock data)
    (["generate", "generate_flowfile", "mock", "test_data", "dummy"],
     "org.apache.nifi.processors.standard.GenerateFlowFile"),
    # Logging
    (["log", "debug", "log_attribute", "logattribute"],
     "org.apache.nifi.processors.standard.LogAttribute"),
    (["log_message", "logmessage"],
     "org.apache.nifi.processors.standard.LogMessage"),
    # Normalize / Parse (fallback to ConvertRecord)
    (["normalize", "parse", "reformat"],
     "org.apache.nifi.processors.standard.ConvertRecord"),
    # Transform (generic — JoltTransformJSON as good default for JSON pipelines)
    (["transform", "map", "reshape"],
     "org.apache.nifi.processors.jolt.JoltTransformJSON"),
]


# ---------------------------------------------------------------------------
# Relationship mapping: processor class suffix -> all relationships
# ---------------------------------------------------------------------------

_RELATIONSHIP_MAP: dict[str, list[str]] = {
    # --- Simple success-only (sources / generators) ---
    "GetFile": ["success"],
    "GetSFTP": ["success"],
    "GetFTP": ["success"],
    "ListenHTTP": ["success"],
    "ListenSyslog": ["success", "invalid"],
    "ListenTCP": ["success"],
    "ListenUDP": ["success"],
    "ListFile": ["success"],
    "ListSFTP": ["success"],
    "ListFTP": ["success"],
    "ListS3": ["success"],
    "ListGCSBucket": ["success"],
    "ListAzureBlobStorage_v12": ["success"],
    "ListDatabaseTables": ["success"],
    "GetSQS": ["success"],
    "GetMongo": ["success", "failure"],
    "GetHDFS": ["success", "failure"],
    "GenerateFlowFile": ["success"],
    "ConsumeMQTT": ["success"],
    "ConsumeAMQP": ["success"],
    "ConsumeJMS": ["success"],
    "ConsumeKafka_2_6": ["success"],
    "ConsumeKafkaRecord_2_6": ["success", "parse.failure"],
    "ConsumeGCPubSub": ["success"],
    "ConsumeAzureEventHub": ["success"],
    "ConsumeIMAP": ["success"],
    "SearchElasticsearch": ["hits", "aggregations"],
    "ConsumeElasticsearch": ["hits"],
    "QueryDatabaseTable": ["success"],
    "QueryDatabaseTableRecord": ["success"],
    "ConsumeKinesisStream": ["success"],

    # --- success + failure (most put/output processors) ---
    "PutFile": ["success", "failure"],
    "PutSFTP": ["success", "failure", "reject"],
    "PutFTP": ["success", "failure", "reject"],
    "PutS3Object": ["success", "failure"],
    "PutGCSObject": ["success", "failure"],
    "PutAzureBlobStorage_v12": ["success", "failure"],
    "PutAzureEventHub": ["success", "failure"],
    "PutAzureCosmosDBRecord": ["success", "failure"],
    "PutSQS": ["success", "failure"],
    "PutSNS": ["success", "failure"],
    "PutKinesisStream": ["success", "failure"],
    "PutLambda": ["success", "failure"],
    "PutDynamoDB": ["success", "failure", "unprocessed"],
    "PutCloudWatchMetric": ["success", "failure"],
    "PutMongo": ["success", "failure"],
    "PutMongoRecord": ["success", "failure"],
    "PublishMQTT": ["success", "failure"],
    "PublishAMQP": ["success", "failure"],
    "PublishJMS": ["success", "failure"],
    "PublishKafka_2_6": ["success", "failure"],
    "PublishKafkaRecord_2_6": ["success", "failure"],
    "PublishGCPubSub": ["success", "failure"],
    "PutTCP": ["success", "failure"],
    "PutUDP": ["success", "failure"],
    "PutSyslog": ["success", "failure", "invalid"],
    "PutWebSocket": ["success", "failure"],
    "PutEmail": ["success", "failure"],
    "PutHDFS": ["success", "failure"],
    "PutSlack": ["success", "failure"],

    # --- Database ---
    "ExecuteSQL": ["success", "failure"],
    "ExecuteSQLRecord": ["success", "failure"],
    "PutSQL": ["success", "failure", "retry"],
    "PutDatabaseRecord": ["success", "failure", "retry"],
    "GenerateTableFetch": ["success", "failure"],

    # --- Record processing ---
    "ConvertRecord": ["success", "failure"],
    "QueryRecord": ["failure", "original", "filtered"],
    "UpdateRecord": ["success", "failure"],
    "SplitRecord": ["splits", "original", "failure"],
    "PartitionRecord": ["success", "original", "failure"],
    "ValidateRecord": ["valid", "invalid", "failure"],
    "LookupRecord": ["success", "failure", "matched", "unmatched"],
    "MergeRecord": ["merged", "original", "failure"],

    # --- Routing ---
    "RouteOnAttribute": ["unmatched"],
    "RouteOnContent": ["unmatched"],
    "RouteText": ["unmatched", "original"],

    # --- Content manipulation ---
    "ReplaceText": ["success", "failure"],
    "ExtractText": ["matched", "unmatched"],
    "EvaluateJsonPath": ["matched", "unmatched", "failure"],
    "EvaluateXPath": ["matched", "unmatched", "failure"],
    "EvaluateXQuery": ["matched", "unmatched", "failure"],
    "JoltTransformJSON": ["success", "failure"],
    "SplitJson": ["split", "original", "failure"],
    "SplitText": ["splits", "original", "failure"],
    "SplitXml": ["split", "original", "failure"],
    "SplitAvro": ["split", "original", "failure"],
    "MergeContent": ["merged", "original", "failure"],
    "CompressContent": ["success", "failure"],
    "UnpackContent": ["success", "original", "failure"],
    "EncryptContent": ["success", "failure"],
    "HashContent": ["success", "failure"],
    "Base64EncodeContent": ["success", "failure"],
    "AttributesToJSON": ["success", "failure"],

    # --- HTTP ---
    "InvokeHTTP": ["Original", "Response", "Retry", "No Retry", "Failure"],
    "HandleHttpRequest": ["success"],
    "HandleHttpResponse": ["success", "failure"],
    "GetHTTP": ["success"],

    # --- Fetch variants ---
    "FetchS3Object": ["success", "failure"],
    "FetchGCSObject": ["success", "failure"],
    "FetchAzureBlobStorage_v12": ["success", "failure"],
    "FetchSFTP": ["success", "not.found", "permission.denied", "failure"],
    "FetchFTP": ["success", "not.found", "permission.denied", "failure"],
    "FetchFile": ["success", "not.found", "permission.denied", "failure"],

    # --- Flow control ---
    "Wait": ["success", "expired", "wait", "failure"],
    "Notify": ["success", "failure"],
    "ControlRate": ["success", "failure"],
    "DetectDuplicate": ["non-duplicate", "duplicate", "failure"],

    # --- Scripting ---
    "ExecuteScript": ["success", "failure"],
    "ExecuteGroovyScript": ["success", "failure"],
    "ExecuteProcess": ["success"],
    "ExecuteStreamCommand": ["output stream", "original", "nonzero status"],

    # --- Elasticsearch ---
    "PutElasticsearchJson": ["successful", "errors", "error_responses"],
    "PutElasticsearchRecord": ["successful", "errors", "error_responses"],
    "DeleteByQueryElasticsearch": ["success", "failure"],

    # --- Utility ---
    "LogAttribute": ["success"],
    "LogMessage": ["success"],
    "IdentifyMimeType": ["success"],
    "CountText": ["success", "failure"],

    # --- WebSocket ---
    "ListenWebSocket": ["connected", "text message", "binary message"],
    "ConnectWebSocket": ["connected", "text message", "binary message"],

    # --- UpdateAttribute (special: in nifi-update-attribute-nar) ---
    "UpdateAttribute": ["success"],
}


# ---------------------------------------------------------------------------
# Property builder functions per processor type
# ---------------------------------------------------------------------------

def _get_conn_prop(comp: Component, key: str, default: str = "") -> str:
    if isinstance(comp, (DataSource, DataSink)) and comp.connection is not None:
        val = comp.connection.properties.get(key)
        if val is not None:
            return str(val)
    if isinstance(comp, DataProcessingElement):
        val = comp.config.get(key)
        if val is not None:
            return str(val)
    return default


def _get_config(comp: Component, key: str, default: str = "") -> str:
    if isinstance(comp, DataProcessingElement):
        val = comp.config.get(key)
        if val is not None:
            return str(val)
    return default


def _get_config_dict(comp: Component) -> dict[str, Any]:
    if isinstance(comp, DataProcessingElement):
        return comp.config
    return {}


def _location_or_empty(comp: Component) -> str:
    if isinstance(comp, (DataSource, DataSink)):
        return comp.location or ""
    return ""


def _build_jdbc_url(comp: Component) -> str:
    host = _get_conn_prop(comp, "host", "localhost")
    port = _get_conn_prop(comp, "port", "5432")
    database = _get_conn_prop(comp, "database", "")
    db_type = ""
    if isinstance(comp, (DataSource, DataSink)):
        db_type = comp.type.strip().lower()

    if "mysql" in db_type or "mariadb" in db_type:
        driver = "mysql"
        if not port or port == "5432":
            port = "3306"
    elif "oracle" in db_type:
        driver = "oracle:thin:@"
        if not port or port == "5432":
            port = "1521"
    elif "sqlserver" in db_type or "mssql" in db_type:
        driver = "sqlserver"
        if not port or port == "5432":
            port = "1433"
    elif "h2" in db_type:
        return f"jdbc:h2:{host}"
    elif "sqlite" in db_type:
        return f"jdbc:sqlite:{database or host}"
    else:
        driver = "postgresql"

    return f"jdbc:{driver}://{host}:{port}/{database}"


def _processor_class_suffix(processor_type: str) -> str:
    return processor_type.rsplit(".", 1)[-1] if "." in processor_type else processor_type


# --- Source property builders ---

def _props_kafka_consumer(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Kafka Brokers", _get_conn_prop(comp, "brokers", "{{KAFKA_BROKERS}}"))
        props.setdefault("Topic Name(s)", comp.location)
        props.setdefault("Group ID", _get_conn_prop(comp, "group_id", "nifi-consumer-group"))


def _props_kafka_producer(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Kafka Brokers", _get_conn_prop(comp, "brokers", "{{KAFKA_BROKERS}}"))
        props.setdefault("Topic Name", comp.location)


def _props_get_file(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Input Directory", comp.location)


def _props_put_file(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        raw_path = _get_conn_prop(comp, "path", comp.location)
        directory, _filename = _split_file_sink_path(raw_path)
        props.setdefault("Directory", directory)
        conflict_strategy = _map_put_file_write_mode(_get_conn_prop(comp, "write_mode", ""))
        if conflict_strategy:
            props.setdefault("Conflict Resolution Strategy", conflict_strategy)


def _props_ftp_get(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Hostname", _get_conn_prop(comp, "hostname", _get_conn_prop(comp, "host", "{{FTP_HOST}}")))
        props.setdefault("Port", _get_conn_prop(comp, "port", "21"))
        props.setdefault("Username", _get_conn_prop(comp, "username", "{{FTP_USERNAME}}"))
        props.setdefault("Remote Path", comp.location)


def _props_ftp_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Hostname", _get_conn_prop(comp, "hostname", _get_conn_prop(comp, "host", "{{FTP_HOST}}")))
        props.setdefault("Port", _get_conn_prop(comp, "port", "21"))
        props.setdefault("Username", _get_conn_prop(comp, "username", "{{FTP_USERNAME}}"))
        props.setdefault("Remote Path", comp.location)


def _props_sftp_get(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Hostname", _get_conn_prop(comp, "hostname", _get_conn_prop(comp, "host", "{{SFTP_HOST}}")))
        props.setdefault("Port", _get_conn_prop(comp, "port", "22"))
        props.setdefault("Username", _get_conn_prop(comp, "username", "{{SFTP_USERNAME}}"))
        props.setdefault("Remote Path", comp.location)


def _props_sftp_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Hostname", _get_conn_prop(comp, "hostname", _get_conn_prop(comp, "host", "{{SFTP_HOST}}")))
        props.setdefault("Port", _get_conn_prop(comp, "port", "22"))
        props.setdefault("Username", _get_conn_prop(comp, "username", "{{SFTP_USERNAME}}"))
        props.setdefault("Remote Path", comp.location)


def _props_invoke_http(comp: Component, props: dict[str, str]) -> None:
    loc = _location_or_empty(comp)
    if loc:
        props.setdefault("HTTP URL", loc)
    if isinstance(comp, DataSink):
        props.setdefault("HTTP Method", "POST")
    elif isinstance(comp, DataSource):
        props.setdefault("HTTP Method", "GET")
    else:
        props.setdefault("HTTP Method", _get_config(comp, "method", "GET"))


def _props_listen_http(comp: Component, props: dict[str, str]) -> None:
    loc = _location_or_empty(comp)
    props.setdefault("Listening Port", _get_conn_prop(comp, "port", loc if loc.isdigit() else "8080"))
    props.setdefault("Base Path", _get_conn_prop(comp, "base_path", "/"))


def _props_s3_fetch(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Bucket", _get_conn_prop(comp, "bucket", comp.location))
        props.setdefault("Object Key", _get_conn_prop(comp, "key", "${filename}"))
        props.setdefault("Region", _get_conn_prop(comp, "region", "us-east-1"))


def _props_s3_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Bucket", _get_conn_prop(comp, "bucket", comp.location))
        props.setdefault("Object Key", _get_conn_prop(comp, "key", "${filename}"))
        props.setdefault("Region", _get_conn_prop(comp, "region", "us-east-1"))


def _props_sqs_get(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Queue URL", comp.location)
        props.setdefault("Region", _get_conn_prop(comp, "region", "us-east-1"))


def _props_sqs_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Queue URL", comp.location)
        props.setdefault("Region", _get_conn_prop(comp, "region", "us-east-1"))


def _props_sns_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Amazon Resource Name (ARN)", comp.location)
        props.setdefault("Region", _get_conn_prop(comp, "region", "us-east-1"))


def _props_kinesis_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Amazon Kinesis Stream Name", comp.location)
        props.setdefault("Region", _get_conn_prop(comp, "region", "us-east-1"))


def _props_lambda_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Amazon Lambda Name", comp.location)
        props.setdefault("Region", _get_conn_prop(comp, "region", "us-east-1"))


def _props_dynamodb_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Table Name", comp.location)
        props.setdefault("Hash Key Name", _get_conn_prop(comp, "hash_key", "id"))
        props.setdefault("Region", _get_conn_prop(comp, "region", "us-east-1"))


def _props_cloudwatch_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Namespace", _get_conn_prop(comp, "namespace", "Custom"))
        props.setdefault("MetricName", comp.location)
        props.setdefault("Region", _get_conn_prop(comp, "region", "us-east-1"))


def _props_gcs_fetch(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Bucket", _get_conn_prop(comp, "bucket", comp.location))
        props.setdefault("Name", _get_conn_prop(comp, "key", "${filename}"))


def _props_gcs_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Bucket", _get_conn_prop(comp, "bucket", comp.location))
        props.setdefault("Key", _get_conn_prop(comp, "key", "${filename}"))


def _props_pubsub_consume(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Project ID", _get_conn_prop(comp, "project_id", "{{GCP_PROJECT_ID}}"))
        props.setdefault("Subscription", comp.location)


def _props_pubsub_publish(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Project ID", _get_conn_prop(comp, "project_id", "{{GCP_PROJECT_ID}}"))
        props.setdefault("Topic Name", comp.location)


def _props_azure_blob_fetch(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Container Name", _get_conn_prop(comp, "container", comp.location))
        props.setdefault("Blob Name", _get_conn_prop(comp, "blob", "${filename}"))
        props.setdefault("Storage Account Name", _get_conn_prop(comp, "account", "{{AZURE_STORAGE_ACCOUNT}}"))


def _props_azure_blob_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Container Name", _get_conn_prop(comp, "container", comp.location))
        props.setdefault("Storage Account Name", _get_conn_prop(comp, "account", "{{AZURE_STORAGE_ACCOUNT}}"))


def _props_azure_eventhub_consume(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Event Hub Namespace", _get_conn_prop(comp, "namespace", "{{EVENT_HUB_NAMESPACE}}"))
        props.setdefault("Event Hub Name", comp.location)
        props.setdefault("Consumer Group", _get_conn_prop(comp, "consumer_group", "$Default"))


def _props_azure_eventhub_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Event Hub Namespace", _get_conn_prop(comp, "namespace", "{{EVENT_HUB_NAMESPACE}}"))
        props.setdefault("Event Hub Name", comp.location)


def _props_cosmosdb_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Cosmos DB URI", _get_conn_prop(comp, "uri", "{{COSMOS_DB_URI}}"))
        props.setdefault("Cosmos DB Name", _get_conn_prop(comp, "database", comp.location))
        props.setdefault("Cosmos DB Container ID", _get_conn_prop(comp, "container", "{{COSMOS_DB_CONTAINER}}"))
        props.setdefault("Partition Key", _get_conn_prop(comp, "partition_key", "/id"))


def _props_query_database_table_record(comp: Component, props: dict[str, str]) -> None:
    """QueryDatabaseTableRecord — polls a table incrementally."""
    if isinstance(comp, DataSource):
        props.setdefault("Table Name", comp.location)
        props.setdefault("Database Type", _detect_db_type(comp))
        host = _get_conn_prop(comp, "host", "")
        if host:
            props.setdefault("Database Connection URL", _build_jdbc_url(comp))


def _get_driver_class(comp: Component) -> str:
    db_type = ""
    if isinstance(comp, (DataSource, DataSink)):
        db_type = comp.type.strip().lower()
    if "mysql" in db_type or "mariadb" in db_type:
        return "com.mysql.cj.jdbc.Driver"
    if "oracle" in db_type:
        return "oracle.jdbc.OracleDriver"
    if "sqlserver" in db_type or "mssql" in db_type:
        return "com.microsoft.sqlserver.jdbc.SQLServerDriver"
    if "h2" in db_type:
        return "org.h2.Driver"
    if "sqlite" in db_type:
        return "org.sqlite.JDBC"
    return "org.postgresql.Driver"


def _detect_db_type(comp: Component) -> str:
    db_type = ""
    if isinstance(comp, (DataSource, DataSink)):
        db_type = comp.type.strip().lower()
    if "mysql" in db_type or "mariadb" in db_type:
        return "MySQL"
    if "oracle" in db_type:
        return "Oracle"
    if "sqlserver" in db_type or "mssql" in db_type:
        return "MS SQL 2012+"
    return "PostgreSQL"


def _props_execute_sql(comp: Component, props: dict[str, str]) -> None:
    loc = _location_or_empty(comp)
    if loc:
        props.setdefault("SQL select query", loc)
    host = _get_conn_prop(comp, "host", "")
    if host:
        props.setdefault("Database Connection URL", _build_jdbc_url(comp))


def _props_put_database_record(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Table Name", comp.location)
        props.setdefault("Statement Type",
                         _get_conn_prop(comp, "statement_type", "INSERT"))
        host = _get_conn_prop(comp, "host", "")
        if host:
            props.setdefault("Database Connection URL", _build_jdbc_url(comp))


def _props_mongodb_get(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Mongo URI", _get_conn_prop(comp, "uri",
                         _get_conn_prop(comp, "host", "{{MONGODB_URI}}")))
        props.setdefault("Mongo Database Name", _get_conn_prop(comp, "database", "{{DATABASE_NAME}}"))
        props.setdefault("Mongo Collection Name", comp.location)


def _props_mongodb_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Mongo URI", _get_conn_prop(comp, "uri",
                         _get_conn_prop(comp, "host", "{{MONGODB_URI}}")))
        props.setdefault("Mongo Database Name", _get_conn_prop(comp, "database", "{{DATABASE_NAME}}"))
        props.setdefault("Mongo Collection Name", comp.location)


def _props_elasticsearch_search(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Index", comp.location)
        query = _get_conn_prop(comp, "query", "")
        if query:
            props.setdefault("Query", query)


def _props_elasticsearch_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Index", comp.location)


def _props_mqtt_consume(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Broker URI", _get_conn_prop(comp, "broker", "{{MQTT_BROKER_URI}}"))
        props.setdefault("Topic Filter", comp.location)
        props.setdefault("Quality of Service(QoS)", _get_conn_prop(comp, "qos", "0"))


def _props_mqtt_publish(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Broker URI", _get_conn_prop(comp, "broker", "{{MQTT_BROKER_URI}}"))
        props.setdefault("Topic", comp.location)
        props.setdefault("Quality of Service(QoS)", _get_conn_prop(comp, "qos", "0"))


def _props_amqp_consume(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Host Name", _get_conn_prop(comp, "host", "{{AMQP_HOST}}"))
        props.setdefault("Queue", comp.location)


def _props_amqp_publish(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Host Name", _get_conn_prop(comp, "host", "{{AMQP_HOST}}"))
        props.setdefault("Exchange Name", _get_conn_prop(comp, "exchange", ""))
        props.setdefault("Routing Key", comp.location)


def _props_jms_consume(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Destination Name", comp.location)


def _props_jms_publish(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Destination Name", comp.location)


def _props_syslog_listen(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Protocol", _get_conn_prop(comp, "protocol", "UDP"))
        loc = _location_or_empty(comp)
        props.setdefault("Port", loc if loc.isdigit() else "514")


def _props_syslog_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Hostname", _get_conn_prop(comp, "host", "{{SYSLOG_HOST}}"))
        props.setdefault("Protocol", _get_conn_prop(comp, "protocol", "UDP"))
        loc = _location_or_empty(comp)
        props.setdefault("Port", loc if loc.isdigit() else "514")


def _props_tcp_listen(comp: Component, props: dict[str, str]) -> None:
    loc = _location_or_empty(comp)
    props.setdefault("Port", loc if loc.isdigit() else "9999")


def _props_tcp_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Hostname", _get_conn_prop(comp, "host", "{{TCP_HOST}}"))
        loc = _location_or_empty(comp)
        props.setdefault("Port", loc if loc.isdigit() else "9999")


def _props_udp_listen(comp: Component, props: dict[str, str]) -> None:
    loc = _location_or_empty(comp)
    props.setdefault("Port", loc if loc.isdigit() else "9999")


def _props_udp_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Hostname", _get_conn_prop(comp, "host", "{{UDP_HOST}}"))
        loc = _location_or_empty(comp)
        props.setdefault("Port", loc if loc.isdigit() else "9999")


def _props_hdfs_get(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Directory", comp.location)


def _props_hdfs_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("Directory", comp.location)


def _props_email_consume(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSource):
        props.setdefault("Host Name", _get_conn_prop(comp, "host", "{{IMAP_HOST}}"))
        props.setdefault("Folder", comp.location or "INBOX")


def _props_email_put(comp: Component, props: dict[str, str]) -> None:
    if isinstance(comp, DataSink):
        props.setdefault("SMTP Hostname", _get_conn_prop(comp, "host", "{{SMTP_HOST}}"))
        props.setdefault("From", _get_conn_prop(comp, "from", "{{EMAIL_FROM}}"))
        props.setdefault("To", comp.location)


# --- Processing operation property builders ---

def _props_query_record(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)

    # SELECT columns: "fields" key may be a list or comma-separated string
    fields = config.get("fields", config.get("select", []))
    if isinstance(fields, list) and fields:
        select_clause = ", ".join(str(f) for f in fields)
    elif isinstance(fields, str) and fields:
        select_clause = fields
    else:
        select_clause = "*"

    sql = f"SELECT {select_clause} FROM FLOWFILE"

    # WHERE clause: try "filter", "where", "condition", "sql", "query" in order
    condition = (
        config.get("filter")
        or config.get("where")
        or config.get("condition")
        or config.get("sql")
        or config.get("query")
        or ""
    )
    if condition:
        sql += f" WHERE {condition}"

    # ORDER BY clause
    sort_by = config.get("sort_by", config.get("order_by", ""))
    if sort_by:
        sql += f" ORDER BY {sort_by}"

    # LIMIT clause
    limit = config.get("limit", "")
    if limit:
        sql += f" LIMIT {limit}"

    props.setdefault("filtered", sql)


def _props_route_on_attribute(comp: Component, props: dict[str, str]) -> None:
    props.setdefault("Routing Strategy", "Route to Property name")


def _props_convert_record(_comp: Component, _props: dict[str, str]) -> None:
    pass


def _props_jolt_transform(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    props.setdefault("Jolt Transformation DSL", config.get("dsl", "Chain"))
    spec = config.get("spec", config.get("specification", config.get("jolt_spec", "")))
    if spec:
        if isinstance(spec, (dict, list)):
            spec = json.dumps(spec, ensure_ascii=False)
        props.setdefault("Jolt Specification", str(spec))


def _props_evaluate_json_path(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    props.setdefault("Destination", config.get("destination", "flowfile-attribute"))
    props.setdefault("Return Type", config.get("return_type", "auto-detect"))


def _props_split_json(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    props.setdefault("JsonPath Expression", config.get("expression", config.get("path", "$.*")))


def _props_split_text(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    props.setdefault("Line Split Count", str(config.get("lines", config.get("count", "1"))))


def _props_replace_text(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    props.setdefault("Search Value", config.get("search", config.get("pattern", "")))
    props.setdefault("Replacement Value", config.get("replacement", config.get("replace", "")))
    props.setdefault("Replacement Strategy", config.get("strategy", "Regex Replace"))
    props.setdefault("Evaluation Mode", config.get("mode", "Entire text"))


def _props_merge_content(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    props.setdefault("Merge Strategy", config.get("strategy", "Bin-Packing Algorithm"))
    props.setdefault("Merge Format", config.get("format", "Binary Concatenation"))
    props.setdefault("Minimum Number of Entries",
                     str(config.get("min_entries", config.get("min", "1"))))
    props.setdefault("Maximum Number of Entries",
                     str(config.get("max_entries", config.get("max", "1000"))))


def _props_compress_content(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    operation = ""
    if isinstance(comp, DataProcessingElement):
        operation = comp.operation.strip().lower()
    if "decompress" in operation or "gunzip" in operation or "unzip" in operation:
        props.setdefault("Mode", "decompress")
    else:
        props.setdefault("Mode", config.get("mode", "compress"))
    props.setdefault("Compression Format", config.get("format", "gzip"))


def _props_encrypt_content(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    operation = ""
    if isinstance(comp, DataProcessingElement):
        operation = comp.operation.strip().lower()
    if "decrypt" in operation:
        props.setdefault("Mode", "Decrypt")
    else:
        props.setdefault("Mode", config.get("mode", "Encrypt"))
    props.setdefault("Key Derivation Function", config.get("kdf", "NIFI_PBKDF2_AES_GCM_256"))


def _props_hash_content(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    props.setdefault("Hash Attribute", config.get("attribute", "hash.value"))
    props.setdefault("Hash Algorithm", config.get("algorithm", "SHA-256"))


def _props_base64(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    operation = ""
    if isinstance(comp, DataProcessingElement):
        operation = comp.operation.strip().lower()
    if "decode" in operation:
        props.setdefault("Mode", "Decode")
    else:
        props.setdefault("Mode", config.get("mode", "Encode"))


def _props_execute_script(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    operation = ""
    if isinstance(comp, DataProcessingElement):
        operation = comp.operation.strip().lower()
    if "groovy" in operation:
        props.setdefault("Script Engine", "Groovy")
    elif "javascript" in operation:
        props.setdefault("Script Engine", "ECMAScript")
    elif "lua" in operation:
        props.setdefault("Script Engine", "lua")
    elif "ruby" in operation:
        props.setdefault("Script Engine", "ruby")
    elif "clojure" in operation:
        props.setdefault("Script Engine", "Clojure")
    else:
        props.setdefault("Script Engine", config.get("engine", "python"))
    script_body = config.get("script", config.get("body", config.get("code", "")))
    script_file = config.get("script_file", config.get("file", ""))
    if script_body:
        props.setdefault("Script Body", str(script_body))
    elif script_file:
        props.setdefault("Script File", str(script_file))


def _props_execute_process(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    props.setdefault("Command", config.get("command", config.get("cmd", "")))
    args = config.get("arguments", config.get("args", ""))
    if args:
        props.setdefault("Command Arguments", str(args))


def _props_execute_stream_command(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    props.setdefault("Command Path", config.get("command", config.get("path", "")))
    args = config.get("arguments", config.get("args", ""))
    if args:
        props.setdefault("Command Arguments", str(args))


def _props_control_rate(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    props.setdefault("Rate Control Criteria", config.get("criteria", "data rate"))
    props.setdefault("Maximum Rate", config.get("rate", config.get("max_rate", "100 KB")))


def _props_detect_duplicate(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    props.setdefault("Cache Entry Identifier",
                     config.get("identifier", config.get("key", "${hash.value}")))


def _props_generate_flowfile(comp: Component, props: dict[str, str]) -> None:
    config = _get_config_dict(comp)
    text = config.get("text", config.get("content", config.get("custom_text", "")))
    if text:
        props.setdefault("Custom Text", str(text))
    else:
        props.setdefault("File Size", config.get("size", "0 B"))


def _props_noop(_comp: Component, _props: dict[str, str]) -> None:
    pass


# Mapping: NiFi class name suffix -> property builder function
_PROPERTY_BUILDERS: dict[str, Any] = {
    "ConsumeKafka_2_6": _props_kafka_consumer,
    "ConsumeKafkaRecord_2_6": _props_kafka_consumer,
    "GetFile": _props_get_file,
    "GetSFTP": _props_sftp_get,
    "GetFTP": _props_ftp_get,
    "InvokeHTTP": _props_invoke_http,
    "ListenHTTP": _props_listen_http,
    "FetchS3Object": _props_s3_fetch,
    "PutS3Object": _props_s3_put,
    "GetSQS": _props_sqs_get,
    "PutSQS": _props_sqs_put,
    "PutSNS": _props_sns_put,
    "PutKinesisStream": _props_kinesis_put,
    "PutLambda": _props_lambda_put,
    "PutDynamoDB": _props_dynamodb_put,
    "PutCloudWatchMetric": _props_cloudwatch_put,
    "FetchGCSObject": _props_gcs_fetch,
    "PutGCSObject": _props_gcs_put,
    "ConsumeGCPubSub": _props_pubsub_consume,
    "PublishGCPubSub": _props_pubsub_publish,
    "FetchAzureBlobStorage_v12": _props_azure_blob_fetch,
    "PutAzureBlobStorage_v12": _props_azure_blob_put,
    "ConsumeAzureEventHub": _props_azure_eventhub_consume,
    "PutAzureEventHub": _props_azure_eventhub_put,
    "PutAzureCosmosDBRecord": _props_cosmosdb_put,
    "ExecuteSQL": _props_execute_sql,
    "ExecuteSQLRecord": _props_execute_sql,
    "QueryDatabaseTable": _props_execute_sql,
    "QueryDatabaseTableRecord": _props_query_database_table_record,
    "PutDatabaseRecord": _props_put_database_record,
    "PutSQL": _props_execute_sql,
    "GetMongo": _props_mongodb_get,
    "PutMongo": _props_mongodb_put,
    "PutMongoRecord": _props_mongodb_put,
    "SearchElasticsearch": _props_elasticsearch_search,
    "ConsumeElasticsearch": _props_elasticsearch_search,
    "PutElasticsearchJson": _props_elasticsearch_put,
    "PutElasticsearchRecord": _props_elasticsearch_put,
    "ConsumeMQTT": _props_mqtt_consume,
    "PublishMQTT": _props_mqtt_publish,
    "ConsumeAMQP": _props_amqp_consume,
    "PublishAMQP": _props_amqp_publish,
    "ConsumeJMS": _props_jms_consume,
    "PublishJMS": _props_jms_publish,
    "ListenSyslog": _props_syslog_listen,
    "PutSyslog": _props_syslog_put,
    "ListenTCP": _props_tcp_listen,
    "PutTCP": _props_tcp_put,
    "ListenUDP": _props_udp_listen,
    "PutUDP": _props_udp_put,
    "GetHDFS": _props_hdfs_get,
    "PutHDFS": _props_hdfs_put,
    "ConsumeIMAP": _props_email_consume,
    "PutEmail": _props_email_put,
    "PutFile": _props_put_file,
    "PutSFTP": _props_sftp_put,
    "PutFTP": _props_ftp_put,
    "PublishKafka_2_6": _props_kafka_producer,
    "PublishKafkaRecord_2_6": _props_kafka_producer,
    "LogAttribute": _props_noop,
    "LogMessage": _props_noop,
    "QueryRecord": _props_query_record,
    "RouteOnAttribute": _props_route_on_attribute,
    "RouteOnContent": _props_noop,
    "RouteText": _props_noop,
    "ConvertRecord": _props_convert_record,
    "JoltTransformJSON": _props_jolt_transform,
    "EvaluateJsonPath": _props_evaluate_json_path,
    "EvaluateXPath": _props_noop,
    "EvaluateXQuery": _props_noop,
    "SplitJson": _props_split_json,
    "SplitText": _props_split_text,
    "SplitXml": _props_noop,
    "SplitAvro": _props_noop,
    "SplitRecord": _props_noop,
    "MergeContent": _props_merge_content,
    "MergeRecord": _props_noop,
    "ReplaceText": _props_replace_text,
    "ExtractText": _props_noop,
    "UpdateRecord": _props_noop,
    "PartitionRecord": _props_noop,
    "ValidateRecord": _props_noop,
    "LookupRecord": _props_noop,
    "CompressContent": _props_compress_content,
    "UnpackContent": _props_noop,
    "EncryptContent": _props_encrypt_content,
    "HashContent": _props_hash_content,
    "Base64EncodeContent": _props_base64,
    "UpdateAttribute": _props_noop,
    "AttributesToJSON": _props_noop,
    "ExecuteScript": _props_execute_script,
    "ExecuteGroovyScript": _props_execute_script,
    "ExecuteProcess": _props_execute_process,
    "ExecuteStreamCommand": _props_execute_stream_command,
    "Wait": _props_noop,
    "Notify": _props_noop,
    "ControlRate": _props_control_rate,
    "DetectDuplicate": _props_detect_duplicate,
    "IdentifyMimeType": _props_noop,
    "GenerateFlowFile": _props_generate_flowfile,
    "HandleHttpRequest": _props_noop,
    "HandleHttpResponse": _props_noop,
    "ListenWebSocket": _props_noop,
    "PutWebSocket": _props_noop,
    "ConnectWebSocket": _props_noop,
    "CountText": _props_noop,
    "PutSlack": _props_noop,
    "FetchFile": _props_noop,
    "ListFile": _props_noop,
    "DeleteByQueryElasticsearch": _props_noop,
}


# ---------------------------------------------------------------------------
# Processor-to-service affinity sets
# ---------------------------------------------------------------------------

# Processors that require a DB connection pooling controller service
_DB_PROCESSOR_SUFFIXES: frozenset[str] = frozenset({
    "ExecuteSQL", "ExecuteSQLRecord", "PutSQL", "PutDatabaseRecord",
    "QueryDatabaseTable", "QueryDatabaseTableRecord",
    "GenerateTableFetch", "ListDatabaseTables",
})

# Processors that write records and need a Record Writer service
_RECORD_WRITER_SUFFIXES: frozenset[str] = frozenset({
    "QueryDatabaseTableRecord", "ExecuteSQLRecord",
    "QueryRecord", "ConvertRecord", "UpdateRecord", "SplitRecord",
    "PartitionRecord", "ValidateRecord", "LookupRecord", "MergeRecord",
    "PutElasticsearchRecord", "PutMongoRecord", "PutAzureCosmosDBRecord",
    "ConsumeKafkaRecord_2_6", "PublishKafkaRecord_2_6",
})

# Processors that read records and need a Record Reader service
_RECORD_READER_SUFFIXES: frozenset[str] = frozenset({
    "PutDatabaseRecord",
    "QueryRecord",
    "ConvertRecord", "ValidateRecord", "LookupRecord", "MergeRecord",
    "PartitionRecord", "UpdateRecord", "SplitRecord",
    "PutElasticsearchRecord", "PutMongoRecord", "PutAzureCosmosDBRecord",
})

# Raw PIM connection-property keys that belong on the CS, not the processor
_DB_CONNECTION_KEYS: frozenset[str] = frozenset({
    "host", "port", "database", "username", "password", "user",
    "db", "jdbc_url", "connection_url", "connection_string",
})

# PIM config keys fully consumed by specific property builders.
# These must NOT be passed through to NiFi as raw property names by the generic fallback,
# because the builder translates them into proper NiFi properties (e.g. SQL statements).
_BUILDER_CONSUMED_KEYS: dict[str, frozenset[str]] = {
    "ConvertRecord": frozenset({
        "output_format", "input_format", "format",
    }),
    "PutFile": frozenset({
        "path", "write_mode", "filename", "file_name", "directory",
    }),
    "QueryRecord": frozenset({
        "filter", "where", "condition", "sql", "query",
        "sort_by", "order_by", "fields", "select", "limit",
    }),
}

_TRANSPARENT_PARSE_CONFIG_KEYS: frozenset[str] = frozenset({
    "output_format", "input_format", "format",
})


def _split_file_sink_path(raw_path: str) -> tuple[str, str]:
    """Return (directory, filename) for a PIM file sink location/path."""
    normalized = (raw_path or "").replace("\\", "/").strip()
    if not normalized:
        return ".", ""

    stripped = normalized.rstrip("/")
    base = posixpath.basename(stripped)
    if "." not in base:
        return stripped or ".", ""

    directory = posixpath.dirname(stripped) or "."
    return directory, base


def _map_put_file_write_mode(raw_mode: str) -> str:
    mode = (raw_mode or "").strip().lower().replace("-", "_").replace(" ", "_")
    if mode in {"overwrite", "replace", "override"}:
        return "replace"
    if mode in {"ignore", "skip", "keep_existing"}:
        return "ignore"
    if mode in {"fail", "error"}:
        return "fail"
    return ""


# ---------------------------------------------------------------------------
# Controller service auto-generation
# ---------------------------------------------------------------------------

def _build_controller_services(plan: "dict[str, Any]", nifi_version: str) -> list[dict[str, Any]]:
    """Build controller service definitions from a pre-planned IDs dict."""
    services: list[dict[str, Any]] = []

    if "dbcp_id" in plan:
        svc_type = "org.apache.nifi.dbcp.DBCPConnectionPool"
        services.append({
            "identifier": plan["dbcp_id"],
            "name": "DatabaseConnectionPool",
            "type": svc_type,
            "bundle": _resolve_service_bundle(svc_type, nifi_version),
            "properties": {
                "Database Connection URL": plan.get("db_url", "{{DB_CONNECTION_URL}}"),
                "Database Driver Class Name": plan.get("db_driver", "org.postgresql.Driver"),
                "Database User": plan.get("db_user", "{{DB_USERNAME}}"),
                "Password": plan.get("db_password", "{{DB_PASSWORD}}"),
            },
            "propertyDescriptors": {},
        })

    if "json_reader_id" in plan:
        svc_type = "org.apache.nifi.json.JsonTreeReader"
        services.append({
            "identifier": plan["json_reader_id"],
            "name": "JsonTreeReader",
            "type": svc_type,
            "bundle": _resolve_service_bundle(svc_type, nifi_version),
            "properties": {},
            "propertyDescriptors": {},
        })

    if "json_writer_id" in plan:
        svc_type = "org.apache.nifi.json.JsonRecordSetWriter"
        services.append({
            "identifier": plan["json_writer_id"],
            "name": "JsonRecordSetWriter",
            "type": svc_type,
            "bundle": _resolve_service_bundle(svc_type, nifi_version),
            "properties": {},
            "propertyDescriptors": {},
        })

    return services


# ===================================================================
# Main Adapter Class
# ===================================================================

class NiFiAdapter(BaseAdapter):
    """
    Rule-based adapter: PIM Flow -> NiFi Flow Definition JSON.

    Covers 95%+ of common NiFi processor types including:
    - Data sources: Kafka, File, FTP/SFTP, HTTP/REST, S3, GCS, Azure Blob,
      MongoDB, Elasticsearch, MQTT, AMQP, JMS, SQS, Syslog, TCP/UDP,
      WebSocket, HDFS, Email, databases (JDBC)
    - Data sinks: same categories + SNS, Lambda, DynamoDB, CloudWatch,
      CosmosDB, Slack, Email (SMTP)
    - Processing: Filter (QueryRecord), Route, Convert, Jolt transform,
      JSON/XML/XPath evaluation, Split, Merge, Replace, Extract,
      Record operations, Compress, Encrypt, Hash, Base64, Script execution,
      System commands, Flow control, Deduplication
    - Controller services: auto-generated DBCP, JSON readers/writers
    """

    def __init__(
        self,
        x_spacing: float = 380.0,
        y_spacing: float = 180.0,
        origin_x: float = 80.0,
        origin_y: float = 80.0,
        nifi_version: str = "2.7.2",
    ) -> None:
        self.x_spacing = x_spacing
        self.y_spacing = y_spacing
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.nifi_version = nifi_version

    def _plan_controller_services(self, components: list[Component]) -> dict[str, Any]:
        """Pre-assign UUIDs for controller services and capture DB connection info."""
        plan: dict[str, Any] = {}
        for comp in components:
            proc_type = self._map_component_to_processor_type(comp)
            suffix = _processor_class_suffix(proc_type)

            if suffix in _DB_PROCESSOR_SUFFIXES and "dbcp_id" not in plan:
                plan["dbcp_id"] = str(uuid4())
                if isinstance(comp, DataSource):
                    plan["db_url"] = _build_jdbc_url(comp)
                    plan["db_driver"] = _get_driver_class(comp)
                    plan["db_user"] = _get_conn_prop(comp, "username", "${db.user}")
                    plan["db_password"] = _get_conn_prop(comp, "password", "${db.password}")
                elif isinstance(comp, DataSink):
                    plan["db_url"] = _build_jdbc_url(comp)
                    plan["db_driver"] = _get_driver_class(comp)
                    plan["db_user"] = _get_conn_prop(comp, "username", "${db.user}")
                    plan["db_password"] = _get_conn_prop(comp, "password", "${db.password}")

            if suffix in _RECORD_WRITER_SUFFIXES and "json_writer_id" not in plan:
                plan["json_writer_id"] = str(uuid4())

            if suffix in _RECORD_READER_SUFFIXES and "json_reader_id" not in plan:
                plan["json_reader_id"] = str(uuid4())

        return plan

    def convert(self, pim: Flow) -> dict[str, Any]:
        components, links = self._normalize_flow_graph(pim)
        self._validate_components_and_links(components=components, links=links)

        positions = self._compute_positions(
            sources=pim.sources,
            processing_elements=pim.processing_elements,
            sinks=pim.sinks,
            links=links,
        )

        flow_group_id = self._new_uuid()
        internal_id_to_uuid = {component.id: self._new_uuid() for component in components}
        components_by_id = {component.id: component for component in components}
        processor_types = {
            component.id: self._map_component_to_processor_type(component)
            for component in components
        }
        outgoing_counts = self._build_outgoing_counts(
            links=links,
            valid_ids=set(components_by_id.keys()),
        )

        # Pre-plan controller services so processors can reference their IDs
        cs_plan = self._plan_controller_services(components)

        processors = [
            self._build_processor(
                component=component,
                processor_uuid=internal_id_to_uuid[component.id],
                processor_type=processor_types[component.id],
                position=positions.get(component.id, (self.origin_x, self.origin_y)),
                auto_terminate=outgoing_counts.get(component.id, 0) == 0,
                cs_plan=cs_plan,
            )
            for component in components
        ]

        connections = [
            self._build_connection(
                link=link,
                flow_group_id=flow_group_id,
                internal_id_to_uuid=internal_id_to_uuid,
                components_by_id=components_by_id,
                processor_types=processor_types,
            )
            for link in links
            if link.from_id in components_by_id and link.to_id in components_by_id
        ]

        controller_services = _build_controller_services(cs_plan, self.nifi_version)

        return {
            "flowContents": {
                "identifier": flow_group_id,
                "name": pim.flow.name,
                "comments": pim.flow.description or "",
                "processors": processors,
                "connections": connections,
                "processGroups": [],
                "remoteProcessGroups": [],
                "inputPorts": [],
                "outputPorts": [],
                "labels": [],
                "funnels": [],
                "controllerServices": controller_services,
            }
        }

    # -------------------------
    # Component collection / validation
    # -------------------------

    def _collect_components(self, pim: Flow) -> list[Component]:
        return [*pim.sources, *pim.processing_elements, *pim.sinks]

    def _normalize_flow_graph(self, pim: Flow) -> tuple[list[Component], list[Link]]:
        """Remove transparent PIM-only processing elements and reconnect their edges."""
        transparent_ids = {
            step.id
            for step in pim.processing_elements
            if self._is_transparent_processing_element(step)
        }
        if not transparent_ids:
            return self._collect_components(pim), list(pim.links)

        components = [
            component
            for component in self._collect_components(pim)
            if component.id not in transparent_ids
        ]
        links = self._rewire_links_around_transparent_nodes(pim.links, transparent_ids)
        return components, links

    def _is_transparent_processing_element(self, component: DataProcessingElement) -> bool:
        operation = component.operation.strip().lower().replace("-", "_").replace(" ", "_")
        if not any(token in operation for token in ("parse_json", "parsejson", "parse")):
            return False

        config_keys = {str(key).lower() for key in component.config.keys()}
        if not config_keys.issubset(_TRANSPARENT_PARSE_CONFIG_KEYS):
            return False

        output_format = str(
            component.config.get("output_format")
            or component.config.get("format")
            or "json"
        ).strip().lower()
        return output_format in {"json", "application/json"}

    def _rewire_links_around_transparent_nodes(
        self,
        links: list[Link],
        transparent_ids: set[str],
    ) -> list[Link]:
        incoming: dict[str, list[Link]] = defaultdict(list)
        outgoing: dict[str, list[Link]] = defaultdict(list)
        passthrough: list[Link] = []

        for link in links:
            if link.to_id in transparent_ids:
                incoming[link.to_id].append(link)
            if link.from_id in transparent_ids:
                outgoing[link.from_id].append(link)
            if link.from_id not in transparent_ids and link.to_id not in transparent_ids:
                passthrough.append(link)

        seen: set[tuple[str, str, str | None]] = {
            (link.from_id, link.to_id, link.data_ref)
            for link in passthrough
        }
        rewired = list(passthrough)

        for transparent_id in transparent_ids:
            for src_link in incoming.get(transparent_id, []):
                for dst_link in outgoing.get(transparent_id, []):
                    data_ref = dst_link.data_ref or src_link.data_ref
                    key = (src_link.from_id, dst_link.to_id, data_ref)
                    if key in seen:
                        continue
                    seen.add(key)
                    rewired.append(Link.model_validate({
                        "from_id": src_link.from_id,
                        "to_id": dst_link.to_id,
                        "data_ref": data_ref,
                    }))

        return rewired

    def _validate_components_and_links(self, components: list[Component], links: list[Link]) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()

        for component in components:
            if component.id in seen:
                duplicates.add(component.id)
            seen.add(component.id)

        if duplicates:
            raise ValueError(f"Duplicate component IDs: {', '.join(sorted(duplicates))}")

        unknown_ids = sorted(
            {ep for link in links for ep in (link.from_id, link.to_id) if ep not in seen}
        )
        if unknown_ids:
            # Warn but don't fail — LLMs sometimes add trigger IDs or other
            # non-component IDs to links.  Those links are simply ignored later
            # by _build_outgoing_counts and the comprehension in convert().
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "Adapter: links reference unknown IDs %s — they will be skipped.",
                unknown_ids,
            )

    def _build_outgoing_counts(self, links: list[Link], valid_ids: set[str]) -> dict[str, int]:
        counts = {cid: 0 for cid in valid_ids}
        for link in links:
            if link.from_id in valid_ids and link.to_id in valid_ids:
                counts[link.from_id] += 1
        return counts

    # -------------------------
    # NiFi processor type mapping
    # -------------------------

    def _map_component_to_processor_type(self, component: Component) -> str:
        if isinstance(component, DataSource):
            return self._match_type(component.type, _SOURCE_TYPE_MAP,
                                    "org.apache.nifi.processors.standard.GenerateFlowFile")
        if isinstance(component, DataSink):
            return self._match_type(component.type, _SINK_TYPE_MAP,
                                    "org.apache.nifi.processors.standard.LogAttribute")
        return self._match_type(component.operation, _OPERATION_MAP,
                                "org.apache.nifi.processors.attributes.UpdateAttribute")

    def _match_type(
        self, value: str, mapping: list[tuple[list[str], str]], fallback: str,
    ) -> str:
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        for keywords, processor_type in mapping:
            for keyword in keywords:
                if keyword in normalized:
                    return processor_type
        return fallback

    # -------------------------
    # Processor building
    # -------------------------

    def _build_processor(
        self,
        component: Component,
        processor_uuid: str,
        processor_type: str,
        position: tuple[float, float],
        auto_terminate: bool,
        cs_plan: "dict[str, Any] | None" = None,
    ) -> dict[str, Any]:
        suffix = _processor_class_suffix(processor_type)
        all_relationships = _RELATIONSHIP_MAP.get(suffix, ["success"])
        default_relationship = self._pick_connection_relationship(suffix)

        if auto_terminate:
            auto_terminated = list(all_relationships)
        else:
            auto_terminated = [r for r in all_relationships if r != default_relationship]

        # Polling sources get a reasonable scheduling period
        scheduling_period = "0 sec"
        if suffix in ("GetFile", "GetFTP", "GetSFTP", "ListFile", "ListFTP", "ListSFTP",
                       "ListS3", "ListGCSBucket", "ListAzureBlobStorage_v12",
                       "QueryDatabaseTable", "QueryDatabaseTableRecord",
                       "GenerateTableFetch", "ListDatabaseTables",
                       "GetHTTP", "GetSQS", "GetMongo", "GetHDFS",
                       "GenerateFlowFile", "ConsumeIMAP"):
            scheduling_period = "60 sec"

        return {
            "identifier": processor_uuid,
            "name": component.name,
            "comments": self._build_processor_comments(component),
            "type": processor_type,
            "bundle": _resolve_bundle(processor_type, self.nifi_version),
            "position": {"x": float(position[0]), "y": float(position[1])},
            "style": {},
            "properties": self._build_processor_properties(component, processor_type, cs_plan or {}),
            "propertyDescriptors": {},
            "schedulingStrategy": "TIMER_DRIVEN",
            "schedulingPeriod": scheduling_period,
            "executionNode": "ALL",
            "penaltyDuration": "30 sec",
            "yieldDuration": "1 sec",
            "bulletinLevel": "WARN",
            "runDurationMillis": 0,
            "concurrentlySchedulableTaskCount": 1,
            "autoTerminatedRelationships": auto_terminated,
        }

    def _build_connection(
        self,
        link: Link,
        flow_group_id: str,
        internal_id_to_uuid: dict[str, str],
        components_by_id: dict[str, Component],
        processor_types: dict[str, str],
    ) -> dict[str, Any]:
        source_component = components_by_id[link.from_id]
        destination_component = components_by_id[link.to_id]
        suffix = _processor_class_suffix(processor_types[link.from_id])
        relationship = self._pick_connection_relationship(suffix)

        return {
            "identifier": self._new_uuid(),
            "name": f"{source_component.name} -> {destination_component.name}",
            "comments": link.data_ref or "",
            "source": {
                "id": internal_id_to_uuid[link.from_id],
                "groupId": flow_group_id,
                "type": "PROCESSOR",
                "name": source_component.name,
            },
            "destination": {
                "id": internal_id_to_uuid[link.to_id],
                "groupId": flow_group_id,
                "type": "PROCESSOR",
                "name": destination_component.name,
            },
            "selectedRelationships": [relationship],
            "backPressureObjectThreshold": 10000,
            "backPressureDataSizeThreshold": "1 GB",
            "flowFileExpiration": "0 sec",
            "labelIndex": 1,
            "zIndex": 0,
            "prioritizers": [],
        }

    def _pick_connection_relationship(self, suffix: str) -> str:
        """Choose the primary 'forward' relationship for connections."""
        special = {
            "QueryRecord": "filtered",
            "MergeContent": "merged",
            "MergeRecord": "merged",
            "SplitJson": "split",
            "SplitXml": "split",
            "SplitText": "splits",
            "SplitAvro": "split",
            "SplitRecord": "splits",
            "ExtractText": "matched",
            "EvaluateJsonPath": "matched",
            "EvaluateXPath": "matched",
            "EvaluateXQuery": "matched",
            "RouteOnAttribute": "unmatched",
            "RouteOnContent": "unmatched",
            "RouteText": "unmatched",
            "DetectDuplicate": "non-duplicate",
            "ValidateRecord": "valid",
            "InvokeHTTP": "Response",
            "ExecuteStreamCommand": "output stream",
            "SearchElasticsearch": "hits",
            "ConsumeElasticsearch": "hits",
            "PutElasticsearchJson": "successful",
            "PutElasticsearchRecord": "successful",
            "ListenWebSocket": "text message",
            "ConnectWebSocket": "text message",
        }
        return special.get(suffix, "success")

    def _build_processor_comments(self, component: Component) -> str:
        if isinstance(component, DataSource):
            return f"Generated from PIM source '{component.id}' ({component.type})"
        if isinstance(component, DataSink):
            return f"Generated from PIM sink '{component.id}' ({component.type})"
        return f"Generated from PIM processing element '{component.id}' ({component.operation})"

    # -------------------------
    # Property building
    # -------------------------

    def _build_processor_properties(
        self,
        component: Component,
        processor_type: str,
        cs_plan: "dict[str, str]",
    ) -> dict[str, str]:
        properties: dict[str, str] = {}

        # Apply type-specific property builder
        suffix = _processor_class_suffix(processor_type)
        builder = _PROPERTY_BUILDERS.get(suffix)
        if builder is not None:
            builder(component, properties)

        # Inject controller-service references where required
        if suffix in _DB_PROCESSOR_SUFFIXES and "dbcp_id" in cs_plan:
            properties["Database Connection Pooling Service"] = cs_plan["dbcp_id"]
            # Remove any raw URL that the builder may have set (it belongs on the CS)
            properties.pop("Database Connection URL", None)

        if suffix in _RECORD_WRITER_SUFFIXES and "json_writer_id" in cs_plan:
            properties["Record Writer"] = cs_plan["json_writer_id"]

        if suffix in _RECORD_READER_SUFFIXES and "json_reader_id" in cs_plan:
            properties["Record Reader"] = cs_plan["json_reader_id"]

        # Merge remaining connection/config properties not yet applied,
        # but skip raw DB credentials — those live on the controller service.
        is_db = suffix in _DB_PROCESSOR_SUFFIXES
        consumed = _BUILDER_CONSUMED_KEYS.get(suffix, frozenset())
        if isinstance(component, (DataSource, DataSink)) and component.connection is not None:
            for key, value in component.connection.properties.items():
                if key not in properties and not key.startswith("pim.") and key not in consumed:
                    if is_db and key in _DB_CONNECTION_KEYS:
                        continue
                    self._set_property(properties, key, value)
        elif isinstance(component, DataProcessingElement):
            for key, value in component.config.items():
                if key not in properties and not key.startswith("pim.") and key not in consumed:
                    self._set_property(properties, key, value)

        return properties

    # -------------------------
    # Property helpers
    # -------------------------

    def _set_property(self, target: dict[str, str], key: str, value: Any) -> None:
        if value is None:
            return
        target[key] = self._serialize_property_value(value)

    def _serialize_property_value(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, tuple):
            value = list(value)
        if isinstance(value, set):
            value = sorted(value, key=lambda item: str(item))
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            return str(value)

    # -------------------------
    # Layout
    # -------------------------

    def _compute_positions(
        self,
        sources: list[DataSource],
        processing_elements: list[DataProcessingElement],
        sinks: list[DataSink],
        links: list[Link],
    ) -> dict[str, tuple[float, float]]:
        source_ids = [c.id for c in sources]
        processing_ids = [c.id for c in processing_elements]
        sink_ids = [c.id for c in sinks]
        component_ids = [*source_ids, *processing_ids, *sink_ids]

        if not component_ids:
            return {}

        kind_depth: dict[str, int] = {}
        for cid in source_ids:
            kind_depth[cid] = 0
        for cid in processing_ids:
            kind_depth[cid] = 1
        for cid in sink_ids:
            kind_depth[cid] = 2

        id_set = set(component_ids)
        outgoing: dict[str, list[str]] = {cid: [] for cid in component_ids}
        incoming_count: dict[str, int] = {cid: 0 for cid in component_ids}

        seen_edges: set[tuple[str, str]] = set()
        for link in links:
            if link.from_id not in id_set or link.to_id not in id_set:
                continue
            edge = (link.from_id, link.to_id)
            if edge in seen_edges:
                continue
            seen_edges.add(edge)
            outgoing[link.from_id].append(link.to_id)
            incoming_count[link.to_id] += 1

        queue = deque(cid for cid in component_ids if incoming_count[cid] == 0)
        local_incoming = dict(incoming_count)
        topo_order: list[str] = []

        while queue:
            current = queue.popleft()
            topo_order.append(current)
            for next_id in outgoing[current]:
                local_incoming[next_id] -= 1
                if local_incoming[next_id] == 0:
                    queue.append(next_id)

        if len(topo_order) != len(component_ids):
            return self._fallback_positions(source_ids, processing_ids, sink_ids)

        depth = {cid: kind_depth[cid] for cid in component_ids}
        for current in topo_order:
            for next_id in outgoing[current]:
                depth[next_id] = max(depth[next_id], depth[current] + 1)

        level_nodes: dict[int, list[str]] = defaultdict(list)
        for cid in topo_order:
            level_nodes[depth[cid]].append(cid)

        positions: dict[str, tuple[float, float]] = {}
        for level in sorted(level_nodes.keys()):
            for index, cid in enumerate(level_nodes[level]):
                positions[cid] = (
                    self.origin_x + level * self.x_spacing,
                    self.origin_y + index * self.y_spacing,
                )
        return positions

    def _fallback_positions(
        self, source_ids: list[str], processing_ids: list[str], sink_ids: list[str],
    ) -> dict[str, tuple[float, float]]:
        positions: dict[str, tuple[float, float]] = {}
        for col, ids in [(0, source_ids), (1, processing_ids), (2, sink_ids)]:
            for row, cid in enumerate(ids):
                positions[cid] = (
                    self.origin_x + col * self.x_spacing,
                    self.origin_y + row * self.y_spacing,
                )
        return positions

    # -------------------------
    # UUID helper
    # -------------------------

    def _new_uuid(self) -> str:
        return str(uuid4())
