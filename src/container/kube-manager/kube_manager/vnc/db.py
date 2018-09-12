# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
#

"""
Kube network manager DB
"""

from cfgm_common.vnc_object_db import VncObjectDBClient, VncObjectEtcdClient

DRIVER_CASS = 'cassandra'
DRIVER_ETCD = 'etcd'


class KubeNetworkManagerDB(object):
    def __init__(self, args, logger):
        self._db_logger = logger

        if args.db_driver == DRIVER_CASS:
            self._cass_driver(args)
        elif args.db_driver == DRIVER_ETCD:
            self._etcd_driver(args)
        else:
            msg = str("Contrail API server supports cassandra and etcd "
                      "backends, but neither of them have been configured.")
            raise NotImplementedError(msg)

    def __getattr__(self, name):
        return getattr(self._object_db, name)

    def _cass_driver(self, args):
        vnc_db = {
            'server_list': args.cassandra_server_list,
            'db_prefix': args.cluster_id,
            'logger': self._db_logger.log,
            'reset_config': False,
        }
        if args.cassandra_user and args.cassandra_password:
            vnc_db['credential'] = {'username': args.cassandra_user,
                                    'password': args.cassandra_password}
        self._object_db = VncObjectDBClient(**vnc_db)

    def _etcd_driver(self, args):
        server = args.etcd_server.split(':')
        vnc_db = {
            'host': server[0],
            'port': server[1],
            'prefix': args.etcd_prefix,
            'logger': self._db_logger.log,
        }
        if args.etcd_user and args.etcd_password:
            vnc_db['credential'] = {'user': args.etcd_user,
                                    'password': args.etcd_password}
        self._object_db = VncObjectEtcdClient(**vnc_db)
