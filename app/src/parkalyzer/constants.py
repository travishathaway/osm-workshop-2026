APP_NAME = "parkalyzer"

SCHEMA_NAME = APP_NAME

OSM_SCHEMA = "public"
OSM_POLYGON_TABLE = "planet_osm_polygon"
OSM_GEOMETRY_COLUMN = "way"
OSM_GEOMETRY_SRID = 3857

GEOMETRY_SRID = 3857

ZENSUS_SCHEMA = "zensus"
ZENSUS_TABLE = "alter_in_5_altersklassen_100m"

DEFAULT_ORS_BASE_URL = "http://localhost:8080"
ORS_MATRIX_PATH = "/ors/v2/matrix/{profile}"
ORS_DIRECTIONS_PATH = "/ors/v2/directions/{profile}"
ORS_DEFAULT_PROFILE = "foot-walking"
ORS_MAX_LOCATIONS = 50
ORS_CONCURRENCY = 25

BUFFER_METERS = 3000
