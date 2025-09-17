/* Minimal subset of parson (MIT) implemented inline for this project. */
#include "parson.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

/* This is a very small, permissive JSON reader sufficient for our fields.
   It supports objects, arrays, strings, numbers, booleans, and null. */

typedef struct json_kv_t { char *key; struct json_value_t *value; } json_kv_t;

struct json_object_t { json_kv_t *kvs; size_t count; };
struct json_array_t  { struct json_value_t **items; size_t count; };
struct json_value_t  {
    JSON_Value_Type type;
    union {
        char *string;
        double number;
        int boolean;
        JSON_Object *object;
        JSON_Array  *array;
    } u;
};

static void *xmalloc(size_t n){ void *p = malloc(n); if(!p) abort(); return p; }
static char *xstrdup(const char *s){ size_t n=strlen(s)+1; char *p=xmalloc(n); memcpy(p,s,n); return p; }

static const char* skip_ws(const char* s){ while(*s && isspace((unsigned char)*s)) s++; return s; }
static const char* parse_string(const char* s, char **out){
    if(*s != '"') return NULL; s++;
    const char* start = s; size_t len=0;
    while(*s && *s!='"'){ if(*s=='\\' && s[1]) s++; s++; len++; }
    if(*s!='"') return NULL; char *str = xmalloc(len+1);
    const char* p = start; char* d = str;
    while(p < s){ if(*p=='\\' && p[1]){ p++; *d++=*p++; } else { *d++=*p++; } }
    *d='\0';
    *out = str; return s+1;
}

static const char* parse_number(const char* s, double *out){
    char *end; double v = strtod(s, &end); if(end==s) return NULL; *out=v; return end;
}

static const char* parse_value(const char* s, JSON_Value **out);

static const char* parse_array(const char* s, JSON_Array **out){
    if(*s != '[') return NULL; s++;
    JSON_Array *arr = xmalloc(sizeof(*arr)); arr->items=NULL; arr->count=0;
    s = skip_ws(s);
    if(*s==']'){ *out=arr; return s+1; }
    while(*s){
        s = skip_ws(s);
        JSON_Value *v=NULL; s = parse_value(s,&v); if(!s) return NULL;
        arr->items = realloc(arr->items, (arr->count+1)*sizeof(*arr->items));
        arr->items[arr->count++] = v;
        s = skip_ws(s);
        if(*s==','){ s++; continue; }
        if(*s==']'){ *out=arr; return s+1; }
        return NULL;
    }
    return NULL;
}

static const char* parse_object(const char* s, JSON_Object **out){
    if(*s != '{') return NULL; s++;
    JSON_Object *obj = xmalloc(sizeof(*obj)); obj->kvs=NULL; obj->count=0;
    s = skip_ws(s);
    if(*s=='}'){ *out=obj; return s+1; }
    while(*s){
        s = skip_ws(s);
        char *key=NULL; s = parse_string(s,&key); if(!s) return NULL;
        s = skip_ws(s); if(*s!=':') return NULL; s++;
        s = skip_ws(s);
        JSON_Value *v=NULL; s = parse_value(s,&v); if(!s) return NULL;
        obj->kvs = realloc(obj->kvs, (obj->count+1)*sizeof(*obj->kvs));
        obj->kvs[obj->count].key = key;
        obj->kvs[obj->count].value = v;
        obj->count++;
        s = skip_ws(s);
        if(*s==','){ s++; continue; }
        if(*s=='}'){ *out=obj; return s+1; }
        return NULL;
    }
    return NULL;
}

static const char* parse_value(const char* s, JSON_Value **out){
    s = skip_ws(s);
    if(*s=='"'){ char *str=NULL; const char* e=parse_string(s,&str); if(!e) return NULL; JSON_Value* v=xmalloc(sizeof(*v)); v->type=JSONString; v->u.string=str; *out=v; return e; }
    if(*s=='{' ){ JSON_Object *o=NULL; const char* e=parse_object(s,&o); if(!e) return NULL; JSON_Value* v=xmalloc(sizeof(*v)); v->type=JSONObject; v->u.object=o; *out=v; return e; }
    if(*s=='[' ){ JSON_Array *a=NULL; const char* e=parse_array(s,&a); if(!e) return NULL; JSON_Value* v=xmalloc(sizeof(*v)); v->type=JSONArray; v->u.array=a; *out=v; return e; }
    if(!strncmp(s,"true",4)){ JSON_Value* v=xmalloc(sizeof(*v)); v->type=JSONBoolean; v->u.boolean=1; *out=v; return s+4; }
    if(!strncmp(s,"false",5)){ JSON_Value* v=xmalloc(sizeof(*v)); v->type=JSONBoolean; v->u.boolean=0; *out=v; return s+5; }
    if(!strncmp(s,"null",4)){ JSON_Value* v=xmalloc(sizeof(*v)); v->type=JSONNull; *out=v; return s+4; }
    double num; const char* e=parse_number(s,&num); if(e){ JSON_Value* v=xmalloc(sizeof(*v)); v->type=JSONNumber; v->u.number=num; *out=v; return e; }
    return NULL;
}

static void json_value_free_internal(JSON_Value* v){
    if(!v) return;
    switch(v->type){
        case JSONString: free(v->u.string); break;
        case JSONObject: {
            JSON_Object *o = v->u.object; if(o){
                for(size_t i=0;i<o->count;i++){ free(o->kvs[i].key); json_value_free_internal(o->kvs[i].value);} free(o->kvs); free(o);
            }
        } break;
        case JSONArray: {
            JSON_Array *a = v->u.array; if(a){ for(size_t i=0;i<a->count;i++) json_value_free_internal(a->items[i]); free(a->items); free(a); }
        } break;
        default: break;
    }
    free(v);
}

JSON_Value* json_parse_file(const char* filename){
    FILE* f = fopen(filename, "rb"); if(!f) return NULL;
    fseek(f,0,SEEK_END); long n = ftell(f); fseek(f,0,SEEK_SET);
    char *buf = xmalloc(n+1); if(fread(buf,1,n,f)!=(size_t)n){ fclose(f); free(buf); return NULL; }
    fclose(f); buf[n]='\0';
    const char* s=buf; JSON_Value* v=NULL; const char* e=parse_value(s,&v); free(buf); if(!e) return NULL; return v;
}

void json_value_free(JSON_Value* v){ json_value_free_internal(v); }

JSON_Object* json_value_get_object(const JSON_Value* v){ return v && v->type==JSONObject ? v->u.object : NULL; }
JSON_Array*  json_value_get_array (const JSON_Value* v){ return v && v->type==JSONArray  ? v->u.array  : NULL; }

static JSON_Value* json_object_get_value(const JSON_Object *o, const char* name){
    if(!o || !name) return NULL;
    for(size_t i=0;i<o->count;i++) if(o->kvs[i].key && !strcmp(o->kvs[i].key,name)) return o->kvs[i].value;
    return NULL;
}

const char* json_object_get_string(const JSON_Object* o, const char* name){
    JSON_Value* v = json_object_get_value(o,name); return (v && v->type==JSONString) ? v->u.string : NULL;
}
double json_object_get_number(const JSON_Object* o, const char* name){
    JSON_Value* v = json_object_get_value(o,name); return (v && v->type==JSONNumber) ? v->u.number : 0.0;
}
int json_object_get_boolean(const JSON_Object* o, const char* name){
    JSON_Value* v = json_object_get_value(o,name); return (v && v->type==JSONBoolean) ? v->u.boolean : 0;
}
JSON_Object* json_object_get_object(const JSON_Object* o, const char* name){
    JSON_Value* v = json_object_get_value(o,name); return (v && v->type==JSONObject) ? v->u.object : NULL;
}
JSON_Array* json_object_get_array(const JSON_Object* o, const char* name){
    JSON_Value* v = json_object_get_value(o,name); return (v && v->type==JSONArray) ? v->u.array : NULL;
}
size_t json_array_get_count(const JSON_Array* a){ return a ? a->count : 0; }
JSON_Object* json_array_get_object(const JSON_Array* a, size_t idx){ if(!a || idx>=a->count) return NULL; JSON_Value* v=a->items[idx]; return v && v->type==JSONObject ? v->u.object : NULL; }

int json_object_has_value(const JSON_Object* o, const char* name){
    return json_object_get_value(o, name) != NULL;
}
