#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#
import json
import datetime

import etcd3

try:
    from cfgm_common.exceptions import NoIdError
except ImportError:
    class NoIdError(Exception):
        pass
from vnc_api import vnc_api
import utils


class VncEtcdClient(object):
    def __init__(self, host, port, prefix, logger, obj_cache_exclude_types,
                 credential, ssl_enabled, ca_certs):
        self._host = host
        self._port = port
        self._prefix = prefix
        self._logger = logger
        self._credential = credential
        self._ssl_enabled = ssl_enabled
        self._ca_certs = ca_certs

        self._client = self._new_client()
        self._obj_cache = EtcdCache(skip_keys=obj_cache_exclude_types)
        self._cache = EtcdCache(ttl=3600)  # 1 hour TTL

    def __getattr__(self, name):
        return getattr(self._client, name)

    def _new_client(self):
        kwargs = {'host': self._host, 'port': self._port}

        if self._credential:
            kwargs['user'] = self._credential['username']
            kwargs['password'] = self._credential['password']

        if self._ssl_enabled:
            kwargs['ca_cert'] = self._credential['ca_cert']
            kwargs['cert_key'] = self._credential['ca_key']

        return etcd3.client(**kwargs)

    def _key_prefix(self, obj_type):
        """Resources prefix for etcd.

        :param (str) obj_type: Type of resource
        :return: (str) full prefix ie: "/contrail/virtual_network"
        """
        return "{prefix}/{type}".format(prefix=self._prefix, type=obj_type)

    def _key_obj(self, obj_type, obj_id):
        """Resource key with resource prefix.

        :param (str) obj_type: Type of resource
        :param (str) obj_id: uuid of object
        :return: (str) full key ie: "/contrail/virtual_network/aaa-bbb-ccc"
        """
        key_prefix = self._key_prefix(obj_type)
        return "{prefix}/{id}".format(prefix=key_prefix, id=obj_id)

    # TODO: handle_exception decorator

    def object_read(self, obj_type, obj_uuids, field_names=None,
                    ret_readonly=False):
        """Read objects from etcd.

        :param (str) obj_type: Resource type.
        :param (List[str]) obj_uuids: List of UUID to fetch.
        :param (List[str]) field_names: List of fields to return.
        :param (boolean) ret_readonly: If True read resource
                                       from cache when possible.
        :return: (List[Dict]) List of resources.
        """
        results = []
        if not obj_uuids:
            return True, results

        for uuid in obj_uuids:
            key = self._key_obj(obj_type, uuid)
            if ret_readonly is True and key in self._obj_cache:
                record = self._obj_cache[key]
                resource = record.resource
            else:
                with self._client.lock(key):
                    resource, kv_meta = self._client.get(key)

                if resource is None:
                    # There is no data in etcd, go to next uuid
                    continue

                resource = json.loads(resource)
                record = EtcdCache.Record(resource=resource, kv_meta=kv_meta)
                self._obj_cache[key] = record

            if field_names is None:
                results.append(resource)
            else:
                results.append({k: v for k, v in resource.items()
                                if k in field_names})
        if not results:
            raise NoIdError(obj_uuids[0])
        return True, results

    def object_list(self, obj_type, parent_uuids=None, back_ref_uuids=None,
                    obj_uuids=None, count=False, filters=None,
                    paginate_start=None, paginate_count=None):
        """Get list of objects uuid.

        For given parent_uuids find all childes type of obj_type
        and for given back_ref_uuids find all bacrefs type of obj_type.

        :param (str) obj_type: Type of resource object
        :param (List[str]) parent_uuids: List of parents uuid
        :param (List[str]) back_ref_uuids: List of backrefs uuid
        :param (List[str]) obj_uuids: ???
        :param (boolean) count: Will return length of results
        :param (dict) filters: Filters to apply on results
        :param (str) paginate_start: Last uuid from previous page
        :param (int) paginate_count: How much to show on page
        :return: (Tuple[boolean, List[str], str]) Tuple with success state,
                 list of uuids and uuid of last uuid in current page
        """
        # prepare filters
        if hasattr(self, '_db_client_mgr'):
            obj_class = self._db_client_mgr.get_resource_class(obj_type)
        else:
            obj_class = getattr(vnc_api, utils.CamelCase(obj_type))
        filters = [f for f in filters if f in obj_class.prop_fields]
        # end prepare filters

        ret_marker = None  # last item for pagination
        anchored_op = True
        results = []  # list of dicts from etcd

        # map obj_type to field in etcd record
        child_keys = {'children': "{}s".format(obj_type),
                      'backrefs': "{}_backrefs".format(obj_type)}
        # tuple of tuples of child_key for map, and uuids given
        base_parent_uuids = (('children', parent_uuids),
                             ('backrefs', back_ref_uuids))
        for key, uuids in base_parent_uuids:
            if uuids:
                _, parents = self.object_read(obj_type, uuids,
                                              ret_readonly=True)
                childes = self._get_childes(parents, obj_type, child_keys[key])
                filtered = self._filter(childes, obj_uuids, filters=filters)
                results.extend(filtered)

        if not parent_uuids and not back_ref_uuids:
            anchored_op = False
            if obj_uuids:
                # take obj_uuids and apply filters
                _, parents = self.object_read(obj_type, obj_uuids,
                                              ret_readonly=True)
                for key in child_keys.values():
                    childes = self._get_childes(parents, obj_type,
                                                child_keys[key])
                    filtered = self._filter(childes, obj_uuids, filters=filters)
                    results.extend(filtered)
            else:
                # grab all resources of obj_type
                resource, _ = self._client.get(self._prefix(obj_type))
                results.extend(json.loads(r) for r in resource)

        if count:
            return True, len(results), None

        # for anchored list with pagination,
        # prune from union of anchors and last uuid is marker
        if paginate_start and anchored_op:
            results, ret_marker = self._paginate(results, paginate_start,
                                                 paginate_count)

        return True, [r['uuid'] for r in results], ret_marker

    def fq_name_to_uuid(self, obj_type, fq_name):
        # TODO: implement IMPORTANT (needs cache)
        raise NotImplementedError("vnc_etcd method not implemented")

    def uuid_to_fq_name(self, uuid):
        # TODO: implement IMPORTANT (needs cache)
        raise NotImplementedError("vnc_etcd method not implemented")

    def _get_childes(self, parents, obj_type, field):
        """Fetch all childes from given field.

        Iterate over parent resources and fetch all childes.

        :param (List[Dict]) parents: List of objects
        :param (str) obj_type: Type of resource
        :param (str) field: Field with child resources
        :return: (gen) Generator of dicts with fetched object
        """
        for parent in parents:
            if field in parent:
                for child in parent[field]:
                    _, child = self.object_read(obj_type, [child['uuid']],
                                                ret_readonly=True)
                    yield child

    def _filter(self, objs, obj_uuids, filters):
        """Filter objects by applying filters.

        :param (List[Dict]) objs: Objects to filter
        :param (List[str]) obj_uuids: ???
        :param (Dict) filters: Dictionary with field filters
        :return: (List[Dict]) List of objects which passed filters
        """
        for obj in objs:
            if not filters:
                if not obj_uuids or (obj_uuids and obj['uuid'] in obj_uuids):
                    yield obj
            else:
                if obj_uuids and obj['uuid'] not in obj_uuids:
                    continue

                yield_obj = True
                for k, v in filters.items():
                    if k not in obj:
                        yield_obj = False
                        break
                    if k in obj and isinstance(obj[k], dict):
                        for f in v:
                            try:
                                f_dict = json.loads(f)
                            except ValueError:
                                continue
                            if f_dict.viewitems() <= obj[k].viewitems():
                                yield_obj = False
                                break
                    if yield_obj is False:
                        break  # do not check next filter

                if yield_obj:
                    yield obj

    def _paginate(self, objs, paginate_start, paginate_count):
        """Paginate objects list.

        :param (List[Dict]) objs: List of objects to paginate
        :param (str) paginate_start: Last uuid from previous page
        :param (int) paginate_count: How much to show on page
        :return: (Tuple[List[Dict], str]) Current page of objects and last uuid
        """
        result = list(sorted(objs, key=lambda x: x['id_perms']['created']))
        idx_start = result.index(paginate_start)
        if idx_start == -1:
            idx_start = 0
        result = result[idx_start:]

        if len(objs) > paginate_count:
            result = result[:paginate_count]
        ret_marker = None if not result else result[-1]
        return result, ret_marker['uuid']


class EtcdCache(object):
    """etcd cache container with TTL records.

    :param ttl (int): Time To Live of records expressed in seconds.
    :param skip_keys: List of object types which should not be cached.
    :example:

        # create cache instance
        cache = EtcdCache(ttl=500, skip_keys=['tag_type'])

        # write record to cache
        key = '/contrail/virtual_network/5ee45236-c435-4006-b4df-ba3442c8a3ec'
        resource, kv_meta = etcd_client.get(key)
        record = EtcdCache.Record(resource=resource, kv_meta=kv_meta)

        cache[key] = record

        # read record from cache
        if key in cache:
            record = cache[key]
            print(record.resource, record.ttl)
    """
    DEFAULT_TTL = 300  # seconds

    class Record(object):
        """Record interface to use in cache.

        :param (int) ttl: Time to live in seconds
        :param (Any) resource: data to store, typically a dictionary
        :param (etcd3.KVMetadata) kv_meta: Meta data from etcd3 client
        """

        def __init__(self, ttl=None, resource=None, kv_meta=None):
            self.ttl = ttl
            self.resource = resource
            self.kv_meta = kv_meta

        def set_ttl(self, sec):
            """Set Time To Live in record.

            Will use TTL from cache container. Can be used to variate
            TTL for every record individually.

            :param (int) sec: How long in seconds this record stays valid
            """
            self.ttl = datetime.datetime.now() + datetime.timedelta(seconds=sec)

    def __init__(self, ttl=None, skip_keys=None):
        self._data = {}
        self._skip_keys = skip_keys if skip_keys is not None else []
        if ttl and isinstance(ttl, int):
            self._ttl = ttl
        else:
            self._ttl = self.DEFAULT_TTL

    def __contains__(self, key):
        """Attempt check if key exists in cache.

        Will try to revoke key if ttl expired, and then return True
        if key is valid and still exist in cache, otherwise will return False.
        """
        self.revoke_ttl(key)
        return key in self._data

    def __getitem__(self, key):
        """Read record from cache.

        Throws KeyError if key doesn't exist.
        """
        return self._data[key]

    def __setitem__(self, key, record):
        """Write new record or replace existing one.

        Write method expects record to be instance of Record.
        If record type is in skip_keys will not be write to cache.
        """
        if not isinstance(record, self.Record):
            msg = "{} expect record to be instance of {}".format(
                self.__class__.__name__, self.Record.__name__)
            raise TypeError(msg)

        for skip in self._skip_keys:
            if skip in key:
                return

        record.set_ttl(self._ttl)
        self._data[key] = record

    def __delitem__(self, key):
        """Revoke key if exists in cache."""
        if key in self._data:
            del self._data[key]

    def revoke_ttl(self, key):
        """Revoke key if TTL expired."""
        if key in self._data:
            now = datetime.datetime.now()
            record = self._data[key]
            if record.ttl < now:
                del self[key]
