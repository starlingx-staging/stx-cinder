#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from sqlalchemy import Boolean, Column, DateTime, Text
from sqlalchemy import Integer, MetaData, String, Table, ForeignKey
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


def MediumText():
    return Text().with_variant(MEDIUMTEXT(), 'mysql')


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    Table('snapshots', meta, autoload=True)

    # New table
    snapshot_fault = Table(
        'snapshot_fault', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('snapshot_id', String(length=36), ForeignKey('snapshots.id'),
               nullable=False),
        Column('message', String(length=255)),
        Column('details', MediumText()),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    if not migrate_engine.has_table(snapshot_fault.name):
        try:
            snapshot_fault.create()
        except Exception:
            LOG.error("Table |%s| not created!", repr(snapshot_fault))
            raise
