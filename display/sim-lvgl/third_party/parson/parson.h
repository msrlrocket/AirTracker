/* parson.h */
#ifndef PARSON_H
#define PARSON_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stddef.h>
typedef struct json_object_t JSON_Object;
typedef struct json_array_t  JSON_Array;
typedef struct json_value_t  JSON_Value;

typedef enum json_value_type {
    JSONError   = 0,
    JSONNull    = 1,
    JSONString  = 2,
    JSONNumber  = 3,
    JSONObject  = 4,
    JSONArray   = 5,
    JSONBoolean = 6
} JSON_Value_Type;

JSON_Value  * json_parse_file(const char *filename);
void          json_value_free(JSON_Value *value);
JSON_Object * json_value_get_object(const JSON_Value *value);
JSON_Array  * json_value_get_array(const JSON_Value *value);
const char  * json_object_get_string(const JSON_Object *object, const char *name);
double        json_object_get_number(const JSON_Object *object, const char *name);
int           json_object_get_boolean(const JSON_Object *object, const char *name);
JSON_Object * json_object_get_object(const JSON_Object *object, const char *name);
JSON_Array  * json_object_get_array(const JSON_Object *object, const char *name);
size_t        json_array_get_count(const JSON_Array *array);
JSON_Object * json_array_get_object(const JSON_Array *array, size_t index);

/* Minimal helper to check key existence */
int           json_object_has_value(const JSON_Object *object, const char *name);

#ifdef __cplusplus
}
#endif

#endif /* PARSON_H */
