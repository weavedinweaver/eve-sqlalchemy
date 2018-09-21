# -*- coding: utf-8 -*-
"""
    Helpers and utils functions

    :copyright: (c) 2013 by Andrew Mleczko and Tomasz Jezierski (Tefnet)
    :license: BSD, see LICENSE for more details.

"""
from __future__ import unicode_literals

import ast
import collections
import copy
import re

from eve.utils import config
from sqlalchemy import inspect
from sqlalchemy.ext.declarative.api import DeclarativeMeta
from flask import g

def merge_dicts(*dicts):
    """
    Given any number of dicts, shallow copy and merge into a new dict,
    precedence goes to key value pairs in latter dicts.

    Source: https://stackoverflow.com/q/38987
    """
    result = {}
    for dictionary in dicts:
        result.update(dictionary)
    return result


def dict_update(d, u):
    for k, v in u.items():
        if isinstance(v, collections.Mapping) and \
           k in d and isinstance(d[k], collections.Mapping):
            dict_update(d[k], v)
        elif k not in d:
            d[k] = u[k]


def remove_none_values(dict_):
    for k, v in list(dict_.items()):
        if v is None:
            del(dict_[k])


def validate_filters(where, resource):
    allowed = config.DOMAIN[resource]['allowed_filters']
    if '*' not in allowed:
        for filt in where:
            key = filt.left.key
            if key not in allowed:
                return "filter on '%s' not allowed" % key
    return None


def sqla_object_to_dict(obj, fields):
    """ Creates a dict containing copies of the requested fields from the
    SQLAlchemy query result """
    if config.LAST_UPDATED not in fields:
        fields.append(config.LAST_UPDATED)
    if config.DATE_CREATED not in fields:
        fields.append(config.DATE_CREATED)
    if config.ETAG not in fields \
            and getattr(config, 'IF_MATCH', True):
        fields.append(config.ETAG)

    result = {}
    for field in map(lambda f: f.split('.', 1)[0], fields):
        try:
            val = obj.__getattribute__(field)

            # If association proxies are embedded, their values must be copied
            # since they are garbage collected when Eve try to encode the
            # response.
            if hasattr(val, 'copy'):
                val = val.copy()

            result[field] = _sanitize_value(val, obj=obj)
        except AttributeError:
            # Ignore if the requested field does not exist
            # (may be wrong embedding parameter)
            pass

    # We have to remove the ETAG if it's None so Eve will add it later again.
    if result.get(config.ETAG, False) is None:
        del(result[config.ETAG])

    return result

def object_as_dict(obj):
    return {c.key: getattr(obj, c.key)
            for c in inspect(obj).mapper.column_attrs}

def _sanitize_value(value, obj=None):
    if isinstance(value.__class__, DeclarativeMeta):
        try:
            for embedded_fields in g.config_setting[0].DOMAIN[g.config_setting[1]]['embedded_fields']:
                embedded_attr = getattr(obj, embedded_fields)
                if embedded_attr and embedded_attr[0].__mapper__.class_ == value.__mapper__.class_:
                    return dict([(k, _sanitize_value(v)) for k, v in object_as_dict(value).iteritems()])
        except:
            return _get_id(value)
        return _get_id(value)
    elif isinstance(value, collections.Mapping):
        return dict([(k, _sanitize_value(v)) for k, v in value.items()])
    elif isinstance(value, collections.MutableSequence):
        return [_sanitize_value(v, obj=obj) for v in value]
    elif isinstance(value, collections.Set):
        return set(_sanitize_value(v) for v in value)
    else:
        return copy.copy(value)


def _get_id(obj):
    resource = _get_resource(obj)
    return getattr(obj, config.DOMAIN[resource]['id_field'])


def extract_sort_arg(req):
    if req.sort:
        if re.match('^[-,.\w]+$', req.sort):
            arg = []
            for s in req.sort.split(','):
                if s.startswith('-'):
                    arg.append([s[1:], -1])
                else:
                    arg.append([s])
            return arg
        else:
            return ast.literal_eval(req.sort)
    else:
        return None


def rename_relationship_fields_in_sort_args(model, sort):
    result = []
    rename_mapping = _get_relationship_to_id_field_rename_mapping(model)
    for t in sort:
        if t[0] in rename_mapping:
            t = list(t)
            t[0] = rename_mapping[t[0]]
            t = tuple(t)
        result.append(t)
    return result


def rename_relationship_fields_in_dict(model, dict_):
    result = {}
    rename_mapping = _get_relationship_to_id_field_rename_mapping(model)
    for k, v in dict_.items():
        if k in rename_mapping:
            result[rename_mapping[k]] = v
        else:
            result[k] = v
    return result


def rename_relationship_fields_in_str(model, str_):
    rename_mapping = _get_relationship_to_id_field_rename_mapping(model)
    for k, v in rename_mapping.items():
        str_ = re.sub(r'\b%s\b' % k, v, str_)
    return str_


def _get_relationship_to_id_field_rename_mapping(model):
    result = {}
    resource = _get_resource(model)
    schema = config.DOMAIN[resource]['schema']
    for field, field_schema in schema.items():
        if 'local_id_field' in field_schema:
            result[field] = field_schema['local_id_field']
    return result


def _get_resource(model_or_obj):
    if isinstance(model_or_obj.__class__, DeclarativeMeta):
        model = model_or_obj.__class__
    else:
        model = model_or_obj
    for resource, settings in config.DOMAIN.items():
        if settings['datasource']['source'] == model.__name__:
            return resource
