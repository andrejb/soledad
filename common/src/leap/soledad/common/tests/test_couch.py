# -*- coding: utf-8 -*-
# test_couch.py
# Copyright (C) 2013 LEAP
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


"""
Test ObjectStore and Couch backend bits.
"""


import json

from urlparse import urljoin
from couchdb.client import Server

from testscenarios import TestWithScenarios

from u1db import errors as u1db_errors
from u1db import SyncTarget
from u1db import vectorclock

from leap.soledad.common import couch
from leap.soledad.common import errors

from leap.soledad.common.tests import u1db_tests as tests
from leap.soledad.common.tests.util import CouchDBTestCase
from leap.soledad.common.tests.util import make_local_db_and_target
from leap.soledad.common.tests.util import sync_via_synchronizer

from leap.soledad.common.tests.u1db_tests import test_backends
from leap.soledad.common.tests.u1db_tests import DatabaseBaseTests
from leap.soledad.common.tests.u1db_tests import TestCaseWithServer

from u1db.backends.inmemory import InMemoryIndex


# -----------------------------------------------------------------------------
# The following tests come from `u1db.tests.test_common_backend`.
# -----------------------------------------------------------------------------

class TestCouchBackendImpl(CouchDBTestCase):

    def test__allocate_doc_id(self):
        db = couch.CouchDatabase.open_database(
            urljoin(
                'http://localhost:' + str(self.wrapper.port),
                'u1db_tests'
            ),
            create=True,
            ensure_ddocs=True)
        doc_id1 = db._allocate_doc_id()
        self.assertTrue(doc_id1.startswith('D-'))
        self.assertEqual(34, len(doc_id1))
        int(doc_id1[len('D-'):], 16)
        self.assertNotEqual(doc_id1, db._allocate_doc_id())


# -----------------------------------------------------------------------------
# The following tests come from `u1db.tests.test_backends`.
# -----------------------------------------------------------------------------

def make_couch_database_for_test(test, replica_uid):
    port = str(test.wrapper.port)
    return couch.CouchDatabase.open_database(
        urljoin('http://localhost:' + port, replica_uid),
        create=True,
        replica_uid=replica_uid or 'test',
        ensure_ddocs=True)


def copy_couch_database_for_test(test, db):
    port = str(test.wrapper.port)
    couch_url = 'http://localhost:' + port
    new_dbname = db._replica_uid + '_copy'
    new_db = couch.CouchDatabase.open_database(
        urljoin(couch_url, new_dbname),
        create=True,
        replica_uid=db._replica_uid or 'test')
    # copy all docs
    session = couch.Session()
    old_couch_db = Server(couch_url, session=session)[db._replica_uid]
    new_couch_db = Server(couch_url, session=session)[new_dbname]
    for doc_id in old_couch_db:
        doc = old_couch_db.get(doc_id)
        # bypass u1db_config document
        if doc_id == 'u1db_config':
            pass
        # copy design docs
        elif doc_id.startswith('_design'):
            del doc['_rev']
            new_couch_db.save(doc)
        # copy u1db docs
        elif 'u1db_rev' in doc:
            new_doc = {
                '_id': doc['_id'],
                'u1db_transactions': doc['u1db_transactions'],
                'u1db_rev': doc['u1db_rev']
            }
            attachments = []
            if ('u1db_conflicts' in doc):
                new_doc['u1db_conflicts'] = doc['u1db_conflicts']
                for c_rev in doc['u1db_conflicts']:
                    attachments.append('u1db_conflict_%s' % c_rev)
            new_couch_db.save(new_doc)
            # save conflict data
            attachments.append('u1db_content')
            for att_name in attachments:
                att = old_couch_db.get_attachment(doc_id, att_name)
                if (att is not None):
                    new_couch_db.put_attachment(new_doc, att,
                                                filename=att_name)
    # cleanup connections to prevent file descriptor leaking
    return new_db


def make_document_for_test(test, doc_id, rev, content, has_conflicts=False):
    return couch.CouchDocument(
        doc_id, rev, content, has_conflicts=has_conflicts)


COUCH_SCENARIOS = [
    ('couch', {'make_database_for_test': make_couch_database_for_test,
               'copy_database_for_test': copy_couch_database_for_test,
               'make_document_for_test': make_document_for_test, }),
]


class CouchTests(
        TestWithScenarios, test_backends.AllDatabaseTests, CouchDBTestCase):

    scenarios = COUCH_SCENARIOS

    def setUp(self):
        test_backends.AllDatabaseTests.setUp(self)
        # save db info because of test_close
        self._url = self.db._url
        self._dbname = self.db._dbname

    def tearDown(self):
        # if current test is `test_close` we have to use saved objects to
        # delete the database because the close() method will have removed the
        # references needed to do it using the CouchDatabase.
        if self.id().endswith('test_couch.CouchTests.test_close(couch)'):
            session = couch.Session()
            server = Server(url=self._url, session=session)
            del(server[self._dbname])
        else:
            self.db.delete_database()
        test_backends.AllDatabaseTests.tearDown(self)


class CouchDatabaseTests(
        TestWithScenarios,
        test_backends.LocalDatabaseTests,
        CouchDBTestCase):

    scenarios = COUCH_SCENARIOS

    def tearDown(self):
        self.db.delete_database()
        test_backends.LocalDatabaseTests.tearDown(self)


class CouchValidateGenNTransIdTests(
        TestWithScenarios,
        test_backends.LocalDatabaseValidateGenNTransIdTests,
        CouchDBTestCase):

    scenarios = COUCH_SCENARIOS

    def tearDown(self):
        self.db.delete_database()
        test_backends.LocalDatabaseValidateGenNTransIdTests.tearDown(self)


class CouchValidateSourceGenTests(
        TestWithScenarios,
        test_backends.LocalDatabaseValidateSourceGenTests,
        CouchDBTestCase):

    scenarios = COUCH_SCENARIOS

    def tearDown(self):
        self.db.delete_database()
        test_backends.LocalDatabaseValidateSourceGenTests.tearDown(self)


class CouchWithConflictsTests(
        TestWithScenarios,
        test_backends.LocalDatabaseWithConflictsTests,
        CouchDBTestCase):

        scenarios = COUCH_SCENARIOS

        def tearDown(self):
            self.db.delete_database()
            test_backends.LocalDatabaseWithConflictsTests.tearDown(self)


# Notice: the CouchDB backend does not have indexing capabilities, so we do
# not test indexing now.

# class CouchIndexTests(test_backends.DatabaseIndexTests, CouchDBTestCase):
#
#     scenarios = COUCH_SCENARIOS
#
#     def tearDown(self):
#         self.db.delete_database()
#         test_backends.DatabaseIndexTests.tearDown(self)


# -----------------------------------------------------------------------------
# The following tests come from `u1db.tests.test_sync`.
# -----------------------------------------------------------------------------

target_scenarios = [
    ('local', {'create_db_and_target': make_local_db_and_target}), ]


simple_doc = tests.simple_doc
nested_doc = tests.nested_doc


class CouchDatabaseSyncTargetTests(
        TestWithScenarios,
        DatabaseBaseTests,
        TestCaseWithServer,
        CouchDBTestCase):

    # TODO: implement _set_trace_hook(_shallow) in CouchSyncTarget so
    #       skipped tests can be succesfully executed.

    # whitebox true means self.db is the actual local db object
    # against which the sync is performed
    whitebox = True

    scenarios = (tests.multiply_scenarios(COUCH_SCENARIOS, target_scenarios))

    def set_trace_hook(self, callback, shallow=False):
        setter = (self.st._set_trace_hook if not shallow else
                  self.st._set_trace_hook_shallow)
        try:
            setter(callback)
        except NotImplementedError:
            self.skipTest("%s does not implement _set_trace_hook"
                          % (self.st.__class__.__name__,))

    def setUp(self):
        CouchDBTestCase.setUp(self)
        # from DatabaseBaseTests.setUp
        self.db = self.create_database('test')
        # from TestCaseWithServer.setUp
        self.server = self.server_thread = self.port = None
        # other stuff
        self.db, self.st = self.create_db_and_target(self)
        self.other_changes = []

    def tearDown(self):
        CouchDBTestCase.tearDown(self)
        # from TestCaseWithServer.tearDown
        if self.server is not None:
            self.server.shutdown()
            self.server_thread.join()
            self.server.server_close()
        if self.port:
            self.port.stopListening()
        # from DatabaseBaseTests.tearDown
        if hasattr(self, 'db') and self.db is not None:
            self.db.close()

    def receive_doc(self, doc, gen, trans_id):
        self.other_changes.append(
            (doc.doc_id, doc.rev, doc.get_json(), gen, trans_id))

    def test_sync_exchange_returns_many_new_docs(self):
        # This test was replicated to allow dictionaries to be compared after
        # JSON expansion (because one dictionary may have many different
        # serialized representations).
        doc = self.db.create_doc_from_json(simple_doc)
        doc2 = self.db.create_doc_from_json(nested_doc)
        self.assertTransactionLog([doc.doc_id, doc2.doc_id], self.db)
        new_gen, _ = self.st.sync_exchange(
            [], 'other-replica', last_known_generation=0,
            last_known_trans_id=None, return_doc_cb=self.receive_doc)
        self.assertTransactionLog([doc.doc_id, doc2.doc_id], self.db)
        self.assertEqual(2, new_gen)
        self.assertEqual(
            [(doc.doc_id, doc.rev, json.loads(simple_doc), 1),
             (doc2.doc_id, doc2.rev, json.loads(nested_doc), 2)],
            [c[:-3] + (json.loads(c[-3]), c[-2]) for c in self.other_changes])
        if self.whitebox:
            self.assertEqual(
                self.db._last_exchange_log['return'],
                {'last_gen': 2, 'docs':
                 [(doc.doc_id, doc.rev), (doc2.doc_id, doc2.rev)]})

    def test_get_sync_target(self):
        self.assertIsNot(None, self.st)

    def test_get_sync_info(self):
        self.assertEqual(
            ('test', 0, '', 0, ''), self.st.get_sync_info('other'))

    def test_create_doc_updates_sync_info(self):
        self.assertEqual(
            ('test', 0, '', 0, ''), self.st.get_sync_info('other'))
        self.db.create_doc_from_json(simple_doc)
        self.assertEqual(1, self.st.get_sync_info('other')[1])

    def test_record_sync_info(self):
        self.st.record_sync_info('replica', 10, 'T-transid')
        self.assertEqual(
            ('test', 0, '', 10, 'T-transid'), self.st.get_sync_info('replica'))

    def test_sync_exchange(self):
        docs_by_gen = [
            (self.make_document('doc-id', 'replica:1', simple_doc), 10,
             'T-sid')]
        new_gen, trans_id = self.st.sync_exchange(
            docs_by_gen, 'replica', last_known_generation=0,
            last_known_trans_id=None, return_doc_cb=self.receive_doc)
        self.assertGetDoc(self.db, 'doc-id', 'replica:1', simple_doc, False)
        self.assertTransactionLog(['doc-id'], self.db)
        last_trans_id = self.getLastTransId(self.db)
        self.assertEqual(([], 1, last_trans_id),
                         (self.other_changes, new_gen, last_trans_id))
        self.assertEqual(10, self.st.get_sync_info('replica')[3])

    def test_sync_exchange_deleted(self):
        doc = self.db.create_doc_from_json('{}')
        edit_rev = 'replica:1|' + doc.rev
        docs_by_gen = [
            (self.make_document(doc.doc_id, edit_rev, None), 10, 'T-sid')]
        new_gen, trans_id = self.st.sync_exchange(
            docs_by_gen, 'replica', last_known_generation=0,
            last_known_trans_id=None, return_doc_cb=self.receive_doc)
        self.assertGetDocIncludeDeleted(
            self.db, doc.doc_id, edit_rev, None, False)
        self.assertTransactionLog([doc.doc_id, doc.doc_id], self.db)
        last_trans_id = self.getLastTransId(self.db)
        self.assertEqual(([], 2, last_trans_id),
                         (self.other_changes, new_gen, trans_id))
        self.assertEqual(10, self.st.get_sync_info('replica')[3])

    def test_sync_exchange_push_many(self):
        docs_by_gen = [
            (self.make_document('doc-id', 'replica:1', simple_doc), 10, 'T-1'),
            (self.make_document('doc-id2', 'replica:1', nested_doc), 11,
             'T-2')]
        new_gen, trans_id = self.st.sync_exchange(
            docs_by_gen, 'replica', last_known_generation=0,
            last_known_trans_id=None, return_doc_cb=self.receive_doc)
        self.assertGetDoc(self.db, 'doc-id', 'replica:1', simple_doc, False)
        self.assertGetDoc(self.db, 'doc-id2', 'replica:1', nested_doc, False)
        self.assertTransactionLog(['doc-id', 'doc-id2'], self.db)
        last_trans_id = self.getLastTransId(self.db)
        self.assertEqual(([], 2, last_trans_id),
                         (self.other_changes, new_gen, trans_id))
        self.assertEqual(11, self.st.get_sync_info('replica')[3])

    def test_sync_exchange_refuses_conflicts(self):
        doc = self.db.create_doc_from_json(simple_doc)
        self.assertTransactionLog([doc.doc_id], self.db)
        new_doc = '{"key": "altval"}'
        docs_by_gen = [
            (self.make_document(doc.doc_id, 'replica:1', new_doc), 10,
             'T-sid')]
        new_gen, _ = self.st.sync_exchange(
            docs_by_gen, 'replica', last_known_generation=0,
            last_known_trans_id=None, return_doc_cb=self.receive_doc)
        self.assertTransactionLog([doc.doc_id], self.db)
        self.assertEqual(
            (doc.doc_id, doc.rev, simple_doc, 1), self.other_changes[0][:-1])
        self.assertEqual(1, new_gen)
        if self.whitebox:
            self.assertEqual(self.db._last_exchange_log['return'],
                             {'last_gen': 1, 'docs': [(doc.doc_id, doc.rev)]})

    def test_sync_exchange_ignores_convergence(self):
        doc = self.db.create_doc_from_json(simple_doc)
        self.assertTransactionLog([doc.doc_id], self.db)
        gen, txid = self.db._get_generation_info()
        docs_by_gen = [
            (self.make_document(doc.doc_id, doc.rev, simple_doc), 10, 'T-sid')]
        new_gen, _ = self.st.sync_exchange(
            docs_by_gen, 'replica', last_known_generation=gen,
            last_known_trans_id=txid, return_doc_cb=self.receive_doc)
        self.assertTransactionLog([doc.doc_id], self.db)
        self.assertEqual(([], 1), (self.other_changes, new_gen))

    def test_sync_exchange_returns_new_docs(self):
        doc = self.db.create_doc_from_json(simple_doc)
        self.assertTransactionLog([doc.doc_id], self.db)
        new_gen, _ = self.st.sync_exchange(
            [], 'other-replica', last_known_generation=0,
            last_known_trans_id=None, return_doc_cb=self.receive_doc)
        self.assertTransactionLog([doc.doc_id], self.db)
        self.assertEqual(
            (doc.doc_id, doc.rev, simple_doc, 1), self.other_changes[0][:-1])
        self.assertEqual(1, new_gen)
        if self.whitebox:
            self.assertEqual(self.db._last_exchange_log['return'],
                             {'last_gen': 1, 'docs': [(doc.doc_id, doc.rev)]})

    def test_sync_exchange_returns_deleted_docs(self):
        doc = self.db.create_doc_from_json(simple_doc)
        self.db.delete_doc(doc)
        self.assertTransactionLog([doc.doc_id, doc.doc_id], self.db)
        new_gen, _ = self.st.sync_exchange(
            [], 'other-replica', last_known_generation=0,
            last_known_trans_id=None, return_doc_cb=self.receive_doc)
        self.assertTransactionLog([doc.doc_id, doc.doc_id], self.db)
        self.assertEqual(
            (doc.doc_id, doc.rev, None, 2), self.other_changes[0][:-1])
        self.assertEqual(2, new_gen)
        if self.whitebox:
            self.assertEqual(self.db._last_exchange_log['return'],
                             {'last_gen': 2, 'docs': [(doc.doc_id, doc.rev)]})

    def test_sync_exchange_getting_newer_docs(self):
        doc = self.db.create_doc_from_json(simple_doc)
        self.assertTransactionLog([doc.doc_id], self.db)
        new_doc = '{"key": "altval"}'
        docs_by_gen = [
            (self.make_document(doc.doc_id, 'test:1|z:2', new_doc), 10,
             'T-sid')]
        new_gen, _ = self.st.sync_exchange(
            docs_by_gen, 'other-replica', last_known_generation=0,
            last_known_trans_id=None, return_doc_cb=self.receive_doc)
        self.assertTransactionLog([doc.doc_id, doc.doc_id], self.db)
        self.assertEqual(([], 2), (self.other_changes, new_gen))

    def test_sync_exchange_with_concurrent_updates_of_synced_doc(self):
        expected = []

        def before_whatschanged_cb(state):
            if state != 'before whats_changed':
                return
            cont = '{"key": "cuncurrent"}'
            conc_rev = self.db.put_doc(
                self.make_document(doc.doc_id, 'test:1|z:2', cont))
            expected.append((doc.doc_id, conc_rev, cont, 3))

        self.set_trace_hook(before_whatschanged_cb)
        doc = self.db.create_doc_from_json(simple_doc)
        self.assertTransactionLog([doc.doc_id], self.db)
        new_doc = '{"key": "altval"}'
        docs_by_gen = [
            (self.make_document(doc.doc_id, 'test:1|z:2', new_doc), 10,
             'T-sid')]
        new_gen, _ = self.st.sync_exchange(
            docs_by_gen, 'other-replica', last_known_generation=0,
            last_known_trans_id=None, return_doc_cb=self.receive_doc)
        self.assertEqual(expected, [c[:-1] for c in self.other_changes])
        self.assertEqual(3, new_gen)

    def test_sync_exchange_with_concurrent_updates(self):

        def after_whatschanged_cb(state):
            if state != 'after whats_changed':
                return
            self.db.create_doc_from_json('{"new": "doc"}')

        self.set_trace_hook(after_whatschanged_cb)
        doc = self.db.create_doc_from_json(simple_doc)
        self.assertTransactionLog([doc.doc_id], self.db)
        new_doc = '{"key": "altval"}'
        docs_by_gen = [
            (self.make_document(doc.doc_id, 'test:1|z:2', new_doc), 10,
             'T-sid')]
        new_gen, _ = self.st.sync_exchange(
            docs_by_gen, 'other-replica', last_known_generation=0,
            last_known_trans_id=None, return_doc_cb=self.receive_doc)
        self.assertEqual(([], 2), (self.other_changes, new_gen))

    def test_sync_exchange_converged_handling(self):
        doc = self.db.create_doc_from_json(simple_doc)
        docs_by_gen = [
            (self.make_document('new', 'other:1', '{}'), 4, 'T-foo'),
            (self.make_document(doc.doc_id, doc.rev, doc.get_json()), 5,
             'T-bar')]
        new_gen, _ = self.st.sync_exchange(
            docs_by_gen, 'other-replica', last_known_generation=0,
            last_known_trans_id=None, return_doc_cb=self.receive_doc)
        self.assertEqual(([], 2), (self.other_changes, new_gen))

    def test_sync_exchange_detect_incomplete_exchange(self):
        def before_get_docs_explode(state):
            if state != 'before get_docs':
                return
            raise u1db_errors.U1DBError("fail")
        self.set_trace_hook(before_get_docs_explode)
        # suppress traceback printing in the wsgiref server
        # self.patch(simple_server.ServerHandler,
        #           'log_exception', lambda h, exc_info: None)
        doc = self.db.create_doc_from_json(simple_doc)
        self.assertTransactionLog([doc.doc_id], self.db)
        self.assertRaises(
            (u1db_errors.U1DBError, u1db_errors.BrokenSyncStream),
            self.st.sync_exchange, [], 'other-replica',
            last_known_generation=0, last_known_trans_id=None,
            return_doc_cb=self.receive_doc)

    def test_sync_exchange_doc_ids(self):
        sync_exchange_doc_ids = getattr(self.st, 'sync_exchange_doc_ids', None)
        if sync_exchange_doc_ids is None:
            self.skipTest("sync_exchange_doc_ids not implemented")
        db2 = self.create_database('test2')
        doc = db2.create_doc_from_json(simple_doc)
        new_gen, trans_id = sync_exchange_doc_ids(
            db2, [(doc.doc_id, 10, 'T-sid')], 0, None,
            return_doc_cb=self.receive_doc)
        self.assertGetDoc(self.db, doc.doc_id, doc.rev, simple_doc, False)
        self.assertTransactionLog([doc.doc_id], self.db)
        last_trans_id = self.getLastTransId(self.db)
        self.assertEqual(([], 1, last_trans_id),
                         (self.other_changes, new_gen, trans_id))
        self.assertEqual(10, self.st.get_sync_info(db2._replica_uid)[3])

    def test__set_trace_hook(self):
        called = []

        def cb(state):
            called.append(state)

        self.set_trace_hook(cb)
        self.st.sync_exchange([], 'replica', 0, None, self.receive_doc)
        self.st.record_sync_info('replica', 0, 'T-sid')
        self.assertEqual(['before whats_changed',
                          'after whats_changed',
                          'before get_docs',
                          'record_sync_info',
                          ],
                         called)

    def test__set_trace_hook_shallow(self):
        st_trace_shallow = self.st._set_trace_hook_shallow
        target_st_trace_shallow = SyncTarget._set_trace_hook_shallow
        same_meth = st_trace_shallow == self.st._set_trace_hook
        same_fun = st_trace_shallow.im_func == target_st_trace_shallow.im_func
        if (same_meth or same_fun):
            # shallow same as full
            expected = ['before whats_changed',
                        'after whats_changed',
                        'before get_docs',
                        'record_sync_info',
                        ]
        else:
            expected = ['sync_exchange', 'record_sync_info']

        called = []

        def cb(state):
            called.append(state)

        self.set_trace_hook(cb, shallow=True)
        self.st.sync_exchange([], 'replica', 0, None, self.receive_doc)
        self.st.record_sync_info('replica', 0, 'T-sid')
        self.assertEqual(expected, called)


# The following tests need that the database have an index, so we fake one.

class IndexedCouchDatabase(couch.CouchDatabase):

    def __init__(self, url, dbname, replica_uid=None, ensure_ddocs=True):
        old_class.__init__(self, url, dbname, replica_uid=replica_uid,
                           ensure_ddocs=ensure_ddocs)
        self._indexes = {}

    def _put_doc(self, old_doc, doc):
        for index in self._indexes.itervalues():
            if old_doc is not None and not old_doc.is_tombstone():
                index.remove_json(old_doc.doc_id, old_doc.get_json())
            if not doc.is_tombstone():
                index.add_json(doc.doc_id, doc.get_json())
        old_class._put_doc(self, old_doc, doc)

    def create_index(self, index_name, *index_expressions):
        if index_name in self._indexes:
            if self._indexes[index_name]._definition == list(
                    index_expressions):
                return
            raise u1db_errors.IndexNameTakenError
        index = InMemoryIndex(index_name, list(index_expressions))
        _, all_docs = self.get_all_docs()
        for doc in all_docs:
            index.add_json(doc.doc_id, doc.get_json())
        self._indexes[index_name] = index

    def delete_index(self, index_name):
        del self._indexes[index_name]

    def list_indexes(self):
        definitions = []
        for idx in self._indexes.itervalues():
            definitions.append((idx._name, idx._definition))
        return definitions

    def get_from_index(self, index_name, *key_values):
        try:
            index = self._indexes[index_name]
        except KeyError:
            raise u1db_errors.IndexDoesNotExist
        doc_ids = index.lookup(key_values)
        result = []
        for doc_id in doc_ids:
            result.append(self._get_doc(doc_id, check_for_conflicts=True))
        return result

    def get_range_from_index(self, index_name, start_value=None,
                             end_value=None):
        """Return all documents with key values in the specified range."""
        try:
            index = self._indexes[index_name]
        except KeyError:
            raise u1db_errors.IndexDoesNotExist
        if isinstance(start_value, basestring):
            start_value = (start_value,)
        if isinstance(end_value, basestring):
            end_value = (end_value,)
        doc_ids = index.lookup_range(start_value, end_value)
        result = []
        for doc_id in doc_ids:
            result.append(self._get_doc(doc_id, check_for_conflicts=True))
        return result

    def get_index_keys(self, index_name):
        try:
            index = self._indexes[index_name]
        except KeyError:
            raise u1db_errors.IndexDoesNotExist
        keys = index.keys()
        # XXX inefficiency warning
        return list(set([tuple(key.split('\x01')) for key in keys]))


# monkey patch CouchDatabase (once) to include virtual indexes
if getattr(couch.CouchDatabase, '_old_class', None) is None:
    old_class = couch.CouchDatabase
    IndexedCouchDatabase._old_class = old_class
    couch.CouchDatabase = IndexedCouchDatabase


sync_scenarios = []
for name, scenario in COUCH_SCENARIOS:
    scenario = dict(scenario)
    scenario['do_sync'] = sync_via_synchronizer
    sync_scenarios.append((name, scenario))
    scenario = dict(scenario)


class CouchDatabaseSyncTests(
        TestWithScenarios,
        DatabaseBaseTests,
        CouchDBTestCase):

    scenarios = sync_scenarios

    def create_database(self, replica_uid, sync_role=None):
        if replica_uid == 'test' and sync_role is None:
            # created up the chain by base class but unused
            return None
        db = self.create_database_for_role(replica_uid, sync_role)
        if sync_role:
            self._use_tracking[db] = (replica_uid, sync_role)
        return db

    def create_database_for_role(self, replica_uid, sync_role):
        # hook point for reuse
        return DatabaseBaseTests.create_database(self, replica_uid)

    def copy_database(self, db, sync_role=None):
        # DO NOT COPY OR REUSE THIS CODE OUTSIDE TESTS: COPYING U1DB DATABASES
        # IS THE WRONG THING TO DO, THE ONLY REASON WE DO SO HERE IS TO TEST
        # THAT WE CORRECTLY DETECT IT HAPPENING SO THAT WE CAN RAISE ERRORS
        # RATHER THAN CORRUPT USER DATA. USE SYNC INSTEAD, OR WE WILL SEND
        # NINJA TO YOUR HOUSE.
        db_copy = self.copy_database_for_test(self, db)
        name, orig_sync_role = self._use_tracking[db]
        self._use_tracking[db_copy] = (
            name + '(copy)', sync_role or orig_sync_role)
        return db_copy

    def sync(self, db_from, db_to, trace_hook=None,
             trace_hook_shallow=None):
        from_name, from_sync_role = self._use_tracking[db_from]
        to_name, to_sync_role = self._use_tracking[db_to]
        if from_sync_role not in ('source', 'both'):
            raise Exception("%s marked for %s use but used as source" %
                            (from_name, from_sync_role))
        if to_sync_role not in ('target', 'both'):
            raise Exception("%s marked for %s use but used as target" %
                            (to_name, to_sync_role))
        return self.do_sync(self, db_from, db_to, trace_hook,
                            trace_hook_shallow)

    def setUp(self):
        self.db = None
        self.db1 = None
        self.db2 = None
        self.db3 = None
        self.db1_copy = None
        self.db2_copy = None
        self._use_tracking = {}
        DatabaseBaseTests.setUp(self)

    def tearDown(self):
        for db in [
            self.db, self.db1, self.db2,
            self.db3, self.db1_copy, self.db2_copy
        ]:
            if db is not None:
                db.delete_database()
                db.close()
        for replica_uid, dbname in [
            ('test1_copy', 'source'),
            ('test2_copy', 'target'),
            ('test3', 'target')
        ]:
            db = self.create_database(replica_uid, dbname)
            db.delete_database()
            # cleanup connections to avoid leaking of file descriptors
            db.close()
        DatabaseBaseTests.tearDown(self)

    def assertLastExchangeLog(self, db, expected):
        log = getattr(db, '_last_exchange_log', None)
        if log is None:
            return
        self.assertEqual(expected, log)

    def test_sync_tracks_db_generation_of_other(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        self.assertEqual(0, self.sync(self.db1, self.db2))
        self.assertEqual(
            (0, ''), self.db1._get_replica_gen_and_trans_id('test2'))
        self.assertEqual(
            (0, ''), self.db2._get_replica_gen_and_trans_id('test1'))
        self.assertLastExchangeLog(
            self.db2,
            {'receive': {'docs': [], 'last_known_gen': 0},
             'return': {'docs': [], 'last_gen': 0}})

    def test_sync_autoresolves(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        doc1 = self.db1.create_doc_from_json(simple_doc, doc_id='doc')
        rev1 = doc1.rev
        doc2 = self.db2.create_doc_from_json(simple_doc, doc_id='doc')
        rev2 = doc2.rev
        self.sync(self.db1, self.db2)
        doc = self.db1.get_doc('doc')
        self.assertFalse(doc.has_conflicts)
        self.assertEqual(doc.rev, self.db2.get_doc('doc').rev)
        v = vectorclock.VectorClockRev(doc.rev)
        self.assertTrue(v.is_newer(vectorclock.VectorClockRev(rev1)))
        self.assertTrue(v.is_newer(vectorclock.VectorClockRev(rev2)))

    def test_sync_autoresolves_moar(self):
        # here we test that when a database that has a conflicted document is
        # the source of a sync, and the target database has a revision of the
        # conflicted document that is newer than the source database's, and
        # that target's database's document's content is the same as the
        # source's document's conflict's, the source's document's conflict gets
        # autoresolved, and the source's document's revision bumped.
        #
        # idea is as follows:
        # A          B
        # a1         -
        #   `------->
        # a1         a1
        # v          v
        # a2         a1b1
        #   `------->
        # a1b1+a2    a1b1
        #            v
        # a1b1+a2    a1b2 (a1b2 has same content as a2)
        #   `------->
        # a3b2       a1b2 (autoresolved)
        #   `------->
        # a3b2       a3b2
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        self.db1.create_doc_from_json(simple_doc, doc_id='doc')
        self.sync(self.db1, self.db2)
        for db, content in [(self.db1, '{}'), (self.db2, '{"hi": 42}')]:
            doc = db.get_doc('doc')
            doc.set_json(content)
            db.put_doc(doc)
        self.sync(self.db1, self.db2)
        # db1 and db2 now both have a doc of {hi:42}, but db1 has a conflict
        doc = self.db1.get_doc('doc')
        rev1 = doc.rev
        self.assertTrue(doc.has_conflicts)
        # set db2 to have a doc of {} (same as db1 before the conflict)
        doc = self.db2.get_doc('doc')
        doc.set_json('{}')
        self.db2.put_doc(doc)
        rev2 = doc.rev
        # sync it across
        self.sync(self.db1, self.db2)
        # tadaa!
        doc = self.db1.get_doc('doc')
        self.assertFalse(doc.has_conflicts)
        vec1 = vectorclock.VectorClockRev(rev1)
        vec2 = vectorclock.VectorClockRev(rev2)
        vec3 = vectorclock.VectorClockRev(doc.rev)
        self.assertTrue(vec3.is_newer(vec1))
        self.assertTrue(vec3.is_newer(vec2))
        # because the conflict is on the source, sync it another time
        self.sync(self.db1, self.db2)
        # make sure db2 now has the exact same thing
        self.assertEqual(self.db1.get_doc('doc'), self.db2.get_doc('doc'))

    def test_sync_autoresolves_moar_backwards(self):
        # here we test that when a database that has a conflicted document is
        # the target of a sync, and the source database has a revision of the
        # conflicted document that is newer than the target database's, and
        # that source's database's document's content is the same as the
        # target's document's conflict's, the target's document's conflict gets
        # autoresolved, and the document's revision bumped.
        #
        # idea is as follows:
        # A          B
        # a1         -
        #   `------->
        # a1         a1
        # v          v
        # a2         a1b1
        #   `------->
        # a1b1+a2    a1b1
        #            v
        # a1b1+a2    a1b2 (a1b2 has same content as a2)
        #   <-------'
        # a3b2       a3b2 (autoresolved and propagated)
        self.db1 = self.create_database('test1', 'both')
        self.db2 = self.create_database('test2', 'both')
        self.db1.create_doc_from_json(simple_doc, doc_id='doc')
        self.sync(self.db1, self.db2)
        for db, content in [(self.db1, '{}'), (self.db2, '{"hi": 42}')]:
            doc = db.get_doc('doc')
            doc.set_json(content)
            db.put_doc(doc)
        self.sync(self.db1, self.db2)
        # db1 and db2 now both have a doc of {hi:42}, but db1 has a conflict
        doc = self.db1.get_doc('doc')
        rev1 = doc.rev
        self.assertTrue(doc.has_conflicts)
        revc = self.db1.get_doc_conflicts('doc')[-1].rev
        # set db2 to have a doc of {} (same as db1 before the conflict)
        doc = self.db2.get_doc('doc')
        doc.set_json('{}')
        self.db2.put_doc(doc)
        rev2 = doc.rev
        # sync it across
        self.sync(self.db2, self.db1)
        # tadaa!
        doc = self.db1.get_doc('doc')
        self.assertFalse(doc.has_conflicts)
        vec1 = vectorclock.VectorClockRev(rev1)
        vec2 = vectorclock.VectorClockRev(rev2)
        vec3 = vectorclock.VectorClockRev(doc.rev)
        vecc = vectorclock.VectorClockRev(revc)
        self.assertTrue(vec3.is_newer(vec1))
        self.assertTrue(vec3.is_newer(vec2))
        self.assertTrue(vec3.is_newer(vecc))
        # make sure db2 now has the exact same thing
        self.assertEqual(self.db1.get_doc('doc'), self.db2.get_doc('doc'))

    def test_sync_autoresolves_moar_backwards_three(self):
        # same as autoresolves_moar_backwards, but with three databases (note
        # all the syncs go in the same direction -- this is a more natural
        # scenario):
        #
        # A          B          C
        # a1         -          -
        #   `------->
        # a1         a1         -
        #              `------->
        # a1         a1         a1
        # v          v
        # a2         a1b1       a1
        #  `------------------->
        # a2         a1b1       a2
        #              `------->
        #            a2+a1b1    a2
        #                       v
        # a2         a2+a1b1    a2c1 (same as a1b1)
        #  `------------------->
        # a2c1       a2+a1b1    a2c1
        #   `------->
        # a2b2c1     a2b2c1     a2c1
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'both')
        self.db3 = self.create_database('test3', 'target')
        self.db1.create_doc_from_json(simple_doc, doc_id='doc')
        self.sync(self.db1, self.db2)
        self.sync(self.db2, self.db3)
        for db, content in [(self.db2, '{"hi": 42}'),
                            (self.db1, '{}'),
                            ]:
            doc = db.get_doc('doc')
            doc.set_json(content)
            db.put_doc(doc)
        self.sync(self.db1, self.db3)
        self.sync(self.db2, self.db3)
        # db2 and db3 now both have a doc of {}, but db2 has a
        # conflict
        doc = self.db2.get_doc('doc')
        self.assertTrue(doc.has_conflicts)
        revc = self.db2.get_doc_conflicts('doc')[-1].rev
        self.assertEqual('{}', doc.get_json())
        self.assertEqual(self.db3.get_doc('doc').get_json(), doc.get_json())
        self.assertEqual(self.db3.get_doc('doc').rev, doc.rev)
        # set db3 to have a doc of {hi:42} (same as db2 before the conflict)
        doc = self.db3.get_doc('doc')
        doc.set_json('{"hi": 42}')
        self.db3.put_doc(doc)
        rev3 = doc.rev
        # sync it across to db1
        self.sync(self.db1, self.db3)
        # db1 now has hi:42, with a rev that is newer than db2's doc
        doc = self.db1.get_doc('doc')
        rev1 = doc.rev
        self.assertFalse(doc.has_conflicts)
        self.assertEqual('{"hi": 42}', doc.get_json())
        VCR = vectorclock.VectorClockRev
        self.assertTrue(VCR(rev1).is_newer(VCR(self.db2.get_doc('doc').rev)))
        # so sync it to db2
        self.sync(self.db1, self.db2)
        # tadaa!
        doc = self.db2.get_doc('doc')
        self.assertFalse(doc.has_conflicts)
        # db2's revision of the document is strictly newer than db1's before
        # the sync, and db3's before that sync way back when
        self.assertTrue(VCR(doc.rev).is_newer(VCR(rev1)))
        self.assertTrue(VCR(doc.rev).is_newer(VCR(rev3)))
        self.assertTrue(VCR(doc.rev).is_newer(VCR(revc)))
        # make sure both dbs now have the exact same thing
        self.assertEqual(self.db1.get_doc('doc'), self.db2.get_doc('doc'))

    def test_sync_puts_changes(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        doc = self.db1.create_doc_from_json(simple_doc)
        self.assertEqual(1, self.sync(self.db1, self.db2))
        self.assertGetDoc(self.db2, doc.doc_id, doc.rev, simple_doc, False)
        self.assertEqual(1, self.db1._get_replica_gen_and_trans_id('test2')[0])
        self.assertEqual(1, self.db2._get_replica_gen_and_trans_id('test1')[0])
        self.assertLastExchangeLog(
            self.db2,
            {'receive': {'docs': [(doc.doc_id, doc.rev)],
                         'source_uid': 'test1',
                         'source_gen': 1, 'last_known_gen': 0},
             'return': {'docs': [], 'last_gen': 1}})

    def test_sync_pulls_changes(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        doc = self.db2.create_doc_from_json(simple_doc)
        self.db1.create_index('test-idx', 'key')
        self.assertEqual(0, self.sync(self.db1, self.db2))
        self.assertGetDoc(self.db1, doc.doc_id, doc.rev, simple_doc, False)
        self.assertEqual(1, self.db1._get_replica_gen_and_trans_id('test2')[0])
        self.assertEqual(1, self.db2._get_replica_gen_and_trans_id('test1')[0])
        self.assertLastExchangeLog(
            self.db2,
            {'receive': {'docs': [], 'last_known_gen': 0},
             'return': {'docs': [(doc.doc_id, doc.rev)],
                        'last_gen': 1}})
        self.assertEqual([doc], self.db1.get_from_index('test-idx', 'value'))

    def test_sync_pulling_doesnt_update_other_if_changed(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        doc = self.db2.create_doc_from_json(simple_doc)
        # After the local side has sent its list of docs, before we start
        # receiving the "targets" response, we update the local database with a
        # new record.
        # When we finish synchronizing, we can notice that something locally
        # was updated, and we cannot tell c2 our new updated generation

        def before_get_docs(state):
            if state != 'before get_docs':
                return
            self.db1.create_doc_from_json(simple_doc)

        self.assertEqual(0, self.sync(self.db1, self.db2,
                                      trace_hook=before_get_docs))
        self.assertLastExchangeLog(
            self.db2,
            {'receive': {'docs': [], 'last_known_gen': 0},
             'return': {'docs': [(doc.doc_id, doc.rev)],
                        'last_gen': 1}})
        self.assertEqual(1, self.db1._get_replica_gen_and_trans_id('test2')[0])
        # c2 should not have gotten a '_record_sync_info' call, because the
        # local database had been updated more than just by the messages
        # returned from c2.
        self.assertEqual(
            (0, ''), self.db2._get_replica_gen_and_trans_id('test1'))

    def test_sync_doesnt_update_other_if_nothing_pulled(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        self.db1.create_doc_from_json(simple_doc)

        def no_record_sync_info(state):
            if state != 'record_sync_info':
                return
            self.fail('SyncTarget.record_sync_info was called')
        self.assertEqual(1, self.sync(self.db1, self.db2,
                                      trace_hook_shallow=no_record_sync_info))
        self.assertEqual(
            1,
            self.db2._get_replica_gen_and_trans_id(self.db1._replica_uid)[0])

    def test_sync_ignores_convergence(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'both')
        doc = self.db1.create_doc_from_json(simple_doc)
        self.db3 = self.create_database('test3', 'target')
        self.assertEqual(1, self.sync(self.db1, self.db3))
        self.assertEqual(0, self.sync(self.db2, self.db3))
        self.assertEqual(1, self.sync(self.db1, self.db2))
        self.assertLastExchangeLog(
            self.db2,
            {'receive': {'docs': [(doc.doc_id, doc.rev)],
                         'source_uid': 'test1',
                         'source_gen': 1, 'last_known_gen': 0},
             'return': {'docs': [], 'last_gen': 1}})

    def test_sync_ignores_superseded(self):
        self.db1 = self.create_database('test1', 'both')
        self.db2 = self.create_database('test2', 'both')
        doc = self.db1.create_doc_from_json(simple_doc)
        doc_rev1 = doc.rev
        self.db3 = self.create_database('test3', 'target')
        self.sync(self.db1, self.db3)
        self.sync(self.db2, self.db3)
        new_content = '{"key": "altval"}'
        doc.set_json(new_content)
        self.db1.put_doc(doc)
        doc_rev2 = doc.rev
        self.sync(self.db2, self.db1)
        self.assertLastExchangeLog(
            self.db1,
            {'receive': {'docs': [(doc.doc_id, doc_rev1)],
                         'source_uid': 'test2',
                         'source_gen': 1, 'last_known_gen': 0},
             'return': {'docs': [(doc.doc_id, doc_rev2)],
                        'last_gen': 2}})
        self.assertGetDoc(self.db1, doc.doc_id, doc_rev2, new_content, False)

    def test_sync_sees_remote_conflicted(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        doc1 = self.db1.create_doc_from_json(simple_doc)
        doc_id = doc1.doc_id
        doc1_rev = doc1.rev
        self.db1.create_index('test-idx', 'key')
        new_doc = '{"key": "altval"}'
        doc2 = self.db2.create_doc_from_json(new_doc, doc_id=doc_id)
        doc2_rev = doc2.rev
        self.assertTransactionLog([doc1.doc_id], self.db1)
        self.sync(self.db1, self.db2)
        self.assertLastExchangeLog(
            self.db2,
            {'receive': {'docs': [(doc_id, doc1_rev)],
                         'source_uid': 'test1',
                         'source_gen': 1, 'last_known_gen': 0},
             'return': {'docs': [(doc_id, doc2_rev)],
                        'last_gen': 1}})
        self.assertTransactionLog([doc_id, doc_id], self.db1)
        self.assertGetDoc(self.db1, doc_id, doc2_rev, new_doc, True)
        self.assertGetDoc(self.db2, doc_id, doc2_rev, new_doc, False)
        from_idx = self.db1.get_from_index('test-idx', 'altval')[0]
        self.assertEqual(doc2.doc_id, from_idx.doc_id)
        self.assertEqual(doc2.rev, from_idx.rev)
        self.assertTrue(from_idx.has_conflicts)
        self.assertEqual([], self.db1.get_from_index('test-idx', 'value'))

    def test_sync_sees_remote_delete_conflicted(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        doc1 = self.db1.create_doc_from_json(simple_doc)
        doc_id = doc1.doc_id
        self.db1.create_index('test-idx', 'key')
        self.sync(self.db1, self.db2)
        doc2 = self.make_document(doc1.doc_id, doc1.rev, doc1.get_json())
        new_doc = '{"key": "altval"}'
        doc1.set_json(new_doc)
        self.db1.put_doc(doc1)
        self.db2.delete_doc(doc2)
        self.assertTransactionLog([doc_id, doc_id], self.db1)
        self.sync(self.db1, self.db2)
        self.assertLastExchangeLog(
            self.db2,
            {'receive': {'docs': [(doc_id, doc1.rev)],
                         'source_uid': 'test1',
                         'source_gen': 2, 'last_known_gen': 1},
             'return': {'docs': [(doc_id, doc2.rev)],
                        'last_gen': 2}})
        self.assertTransactionLog([doc_id, doc_id, doc_id], self.db1)
        self.assertGetDocIncludeDeleted(self.db1, doc_id, doc2.rev, None, True)
        self.assertGetDocIncludeDeleted(
            self.db2, doc_id, doc2.rev, None, False)
        self.assertEqual([], self.db1.get_from_index('test-idx', 'value'))

    def test_sync_local_race_conflicted(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        doc = self.db1.create_doc_from_json(simple_doc)
        doc_id = doc.doc_id
        doc1_rev = doc.rev
        self.db1.create_index('test-idx', 'key')
        self.sync(self.db1, self.db2)
        content1 = '{"key": "localval"}'
        content2 = '{"key": "altval"}'
        doc.set_json(content2)
        self.db2.put_doc(doc)
        doc2_rev2 = doc.rev
        triggered = []

        def after_whatschanged(state):
            if state != 'after whats_changed':
                return
            triggered.append(True)
            doc = self.make_document(doc_id, doc1_rev, content1)
            self.db1.put_doc(doc)

        self.sync(self.db1, self.db2, trace_hook=after_whatschanged)
        self.assertEqual([True], triggered)
        self.assertGetDoc(self.db1, doc_id, doc2_rev2, content2, True)
        from_idx = self.db1.get_from_index('test-idx', 'altval')[0]
        self.assertEqual(doc.doc_id, from_idx.doc_id)
        self.assertEqual(doc.rev, from_idx.rev)
        self.assertTrue(from_idx.has_conflicts)
        self.assertEqual([], self.db1.get_from_index('test-idx', 'value'))
        self.assertEqual([], self.db1.get_from_index('test-idx', 'localval'))

    def test_sync_propagates_deletes(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'both')
        doc1 = self.db1.create_doc_from_json(simple_doc)
        doc_id = doc1.doc_id
        self.db1.create_index('test-idx', 'key')
        self.sync(self.db1, self.db2)
        self.db2.create_index('test-idx', 'key')
        self.db3 = self.create_database('test3', 'target')
        self.sync(self.db1, self.db3)
        self.db1.delete_doc(doc1)
        deleted_rev = doc1.rev
        self.sync(self.db1, self.db2)
        self.assertLastExchangeLog(
            self.db2,
            {'receive': {'docs': [(doc_id, deleted_rev)],
                         'source_uid': 'test1',
                         'source_gen': 2, 'last_known_gen': 1},
             'return': {'docs': [], 'last_gen': 2}})
        self.assertGetDocIncludeDeleted(
            self.db1, doc_id, deleted_rev, None, False)
        self.assertGetDocIncludeDeleted(
            self.db2, doc_id, deleted_rev, None, False)
        self.assertEqual([], self.db1.get_from_index('test-idx', 'value'))
        self.assertEqual([], self.db2.get_from_index('test-idx', 'value'))
        self.sync(self.db2, self.db3)
        self.assertLastExchangeLog(
            self.db3,
            {'receive': {'docs': [(doc_id, deleted_rev)],
                         'source_uid': 'test2',
                         'source_gen': 2, 'last_known_gen': 0},
             'return': {'docs': [], 'last_gen': 2}})
        self.assertGetDocIncludeDeleted(
            self.db3, doc_id, deleted_rev, None, False)

    def test_sync_propagates_deletes_2(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        self.db1.create_doc_from_json('{"a": "1"}', doc_id='the-doc')
        self.sync(self.db1, self.db2)
        doc1_2 = self.db2.get_doc('the-doc')
        self.db2.delete_doc(doc1_2)
        self.sync(self.db1, self.db2)
        self.assertGetDocIncludeDeleted(
            self.db1, 'the-doc', doc1_2.rev, None, False)

    def test_sync_propagates_resolution(self):
        self.db1 = self.create_database('test1', 'both')
        self.db2 = self.create_database('test2', 'both')
        doc1 = self.db1.create_doc_from_json('{"a": 1}', doc_id='the-doc')
        db3 = self.create_database('test3', 'both')
        self.sync(self.db2, self.db1)
        self.assertEqual(
            self.db1._get_generation_info(),
            self.db2._get_replica_gen_and_trans_id(self.db1._replica_uid))
        self.assertEqual(
            self.db2._get_generation_info(),
            self.db1._get_replica_gen_and_trans_id(self.db2._replica_uid))
        self.sync(db3, self.db1)
        # update on 2
        doc2 = self.make_document('the-doc', doc1.rev, '{"a": 2}')
        self.db2.put_doc(doc2)
        self.sync(self.db2, db3)
        self.assertEqual(db3.get_doc('the-doc').rev, doc2.rev)
        # update on 1
        doc1.set_json('{"a": 3}')
        self.db1.put_doc(doc1)
        # conflicts
        self.sync(self.db2, self.db1)
        self.sync(db3, self.db1)
        self.assertTrue(self.db2.get_doc('the-doc').has_conflicts)
        self.assertTrue(db3.get_doc('the-doc').has_conflicts)
        # resolve
        conflicts = self.db2.get_doc_conflicts('the-doc')
        doc4 = self.make_document('the-doc', None, '{"a": 4}')
        revs = [doc.rev for doc in conflicts]
        self.db2.resolve_doc(doc4, revs)
        doc2 = self.db2.get_doc('the-doc')
        self.assertEqual(doc4.get_json(), doc2.get_json())
        self.assertFalse(doc2.has_conflicts)
        self.sync(self.db2, db3)
        doc3 = db3.get_doc('the-doc')
        self.assertEqual(doc4.get_json(), doc3.get_json())
        self.assertFalse(doc3.has_conflicts)

    def test_sync_supersedes_conflicts(self):
        self.db1 = self.create_database('test1', 'both')
        self.db2 = self.create_database('test2', 'target')
        db3 = self.create_database('test3', 'both')
        doc1 = self.db1.create_doc_from_json('{"a": 1}', doc_id='the-doc')
        self.db2.create_doc_from_json('{"b": 1}', doc_id='the-doc')
        db3.create_doc_from_json('{"c": 1}', doc_id='the-doc')
        self.sync(db3, self.db1)
        self.assertEqual(
            self.db1._get_generation_info(),
            db3._get_replica_gen_and_trans_id(self.db1._replica_uid))
        self.assertEqual(
            db3._get_generation_info(),
            self.db1._get_replica_gen_and_trans_id(db3._replica_uid))
        self.sync(db3, self.db2)
        self.assertEqual(
            self.db2._get_generation_info(),
            db3._get_replica_gen_and_trans_id(self.db2._replica_uid))
        self.assertEqual(
            db3._get_generation_info(),
            self.db2._get_replica_gen_and_trans_id(db3._replica_uid))
        self.assertEqual(3, len(db3.get_doc_conflicts('the-doc')))
        doc1.set_json('{"a": 2}')
        self.db1.put_doc(doc1)
        self.sync(db3, self.db1)
        # original doc1 should have been removed from conflicts
        self.assertEqual(3, len(db3.get_doc_conflicts('the-doc')))

    def test_sync_stops_after_get_sync_info(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        self.db1.create_doc_from_json(tests.simple_doc)
        self.sync(self.db1, self.db2)

        def put_hook(state):
            self.fail("Tracehook triggered for %s" % (state,))

        self.sync(self.db1, self.db2, trace_hook_shallow=put_hook)

    def test_sync_detects_identical_replica_uid(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test1', 'target')
        self.db1.create_doc_from_json(tests.simple_doc, doc_id='doc1')
        self.assertRaises(
            u1db_errors.InvalidReplicaUID, self.sync, self.db1, self.db2)
        # remove the reference to db2 to avoid double deleting on tearDown
        self.db2.close()
        self.db2 = None

    def test_sync_detects_rollback_in_source(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        self.db1.create_doc_from_json(tests.simple_doc, doc_id='doc1')
        self.sync(self.db1, self.db2)
        db1_copy = self.copy_database(self.db1)
        self.db1.create_doc_from_json(tests.simple_doc, doc_id='doc2')
        self.sync(self.db1, self.db2)
        self.assertRaises(
            u1db_errors.InvalidGeneration, self.sync, db1_copy, self.db2)

    def test_sync_detects_rollback_in_target(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        self.db1.create_doc_from_json(tests.simple_doc, doc_id="divergent")
        self.sync(self.db1, self.db2)
        db2_copy = self.copy_database(self.db2)
        self.db2.create_doc_from_json(tests.simple_doc, doc_id='doc2')
        self.sync(self.db1, self.db2)
        self.assertRaises(
            u1db_errors.InvalidGeneration, self.sync, self.db1, db2_copy)

    def test_sync_detects_diverged_source(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        db3 = self.copy_database(self.db1)
        self.db1.create_doc_from_json(tests.simple_doc, doc_id="divergent")
        db3.create_doc_from_json(tests.simple_doc, doc_id="divergent")
        self.sync(self.db1, self.db2)
        self.assertRaises(
            u1db_errors.InvalidTransactionId, self.sync, db3, self.db2)

    def test_sync_detects_diverged_target(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        db3 = self.copy_database(self.db2)
        db3.create_doc_from_json(tests.nested_doc, doc_id="divergent")
        self.db1.create_doc_from_json(tests.simple_doc, doc_id="divergent")
        self.sync(self.db1, self.db2)
        self.assertRaises(
            u1db_errors.InvalidTransactionId, self.sync, self.db1, db3)

    def test_sync_detects_rollback_and_divergence_in_source(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        self.db1.create_doc_from_json(tests.simple_doc, doc_id='doc1')
        self.sync(self.db1, self.db2)
        db1_copy = self.copy_database(self.db1)
        self.db1.create_doc_from_json(tests.simple_doc, doc_id='doc2')
        self.db1.create_doc_from_json(tests.simple_doc, doc_id='doc3')
        self.sync(self.db1, self.db2)
        db1_copy.create_doc_from_json(tests.simple_doc, doc_id='doc2')
        db1_copy.create_doc_from_json(tests.simple_doc, doc_id='doc3')
        self.assertRaises(
            u1db_errors.InvalidTransactionId, self.sync, db1_copy, self.db2)

    def test_sync_detects_rollback_and_divergence_in_target(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        self.db1.create_doc_from_json(tests.simple_doc, doc_id="divergent")
        self.sync(self.db1, self.db2)
        db2_copy = self.copy_database(self.db2)
        self.db2.create_doc_from_json(tests.simple_doc, doc_id='doc2')
        self.db2.create_doc_from_json(tests.simple_doc, doc_id='doc3')
        self.sync(self.db1, self.db2)
        db2_copy.create_doc_from_json(tests.simple_doc, doc_id='doc2')
        db2_copy.create_doc_from_json(tests.simple_doc, doc_id='doc3')
        self.assertRaises(
            u1db_errors.InvalidTransactionId, self.sync, self.db1, db2_copy)

    def test_optional_sync_preserve_json(self):
        self.db1 = self.create_database('test1', 'source')
        self.db2 = self.create_database('test2', 'target')
        cont1 = '{"a": 2}'
        cont2 = '{"b": 3}'
        self.db1.create_doc_from_json(cont1, doc_id="1")
        self.db2.create_doc_from_json(cont2, doc_id="2")
        self.sync(self.db1, self.db2)
        self.assertEqual(cont1, self.db2.get_doc("1").get_json())
        self.assertEqual(cont2, self.db1.get_doc("2").get_json())


class CouchDatabaseExceptionsTests(CouchDBTestCase):

    def setUp(self):
        CouchDBTestCase.setUp(self)
        self.db = couch.CouchDatabase.open_database(
            urljoin('http://127.0.0.1:%d' % self.wrapper.port, 'test'),
            create=True,
            ensure_ddocs=False)  # note that we don't enforce ddocs here

    def tearDown(self):
        self.db.delete_database()
        self.db.close()
        CouchDBTestCase.tearDown(self)

    def test_missing_design_doc_raises(self):
        """
        Test that all methods that access design documents will raise if the
        design docs are not present.
        """
        # _get_generation()
        self.assertRaises(
            errors.MissingDesignDocError,
            self.db._get_generation)
        # _get_generation_info()
        self.assertRaises(
            errors.MissingDesignDocError,
            self.db._get_generation_info)
        # _get_trans_id_for_gen()
        self.assertRaises(
            errors.MissingDesignDocError,
            self.db._get_trans_id_for_gen, 1)
        # _get_transaction_log()
        self.assertRaises(
            errors.MissingDesignDocError,
            self.db._get_transaction_log)
        # whats_changed()
        self.assertRaises(
            errors.MissingDesignDocError,
            self.db.whats_changed)

    def test_missing_design_doc_functions_raises(self):
        """
        Test that all methods that access design documents list functions
        will raise if the functions are not present.
        """
        self.db = couch.CouchDatabase.open_database(
            urljoin('http://127.0.0.1:%d' % self.wrapper.port, 'test'),
            create=True,
            ensure_ddocs=True)
        # erase views from _design/transactions
        transactions = self.db._database['_design/transactions']
        transactions['lists'] = {}
        self.db._database.save(transactions)
        # _get_generation()
        self.assertRaises(
            errors.MissingDesignDocListFunctionError,
            self.db._get_generation)
        # _get_generation_info()
        self.assertRaises(
            errors.MissingDesignDocListFunctionError,
            self.db._get_generation_info)
        # _get_trans_id_for_gen()
        self.assertRaises(
            errors.MissingDesignDocListFunctionError,
            self.db._get_trans_id_for_gen, 1)
        # whats_changed()
        self.assertRaises(
            errors.MissingDesignDocListFunctionError,
            self.db.whats_changed)

    def test_absent_design_doc_functions_raises(self):
        """
        Test that all methods that access design documents list functions
        will raise if the functions are not present.
        """
        self.db = couch.CouchDatabase.open_database(
            urljoin('http://127.0.0.1:%d' % self.wrapper.port, 'test'),
            create=True,
            ensure_ddocs=True)
        # erase views from _design/transactions
        transactions = self.db._database['_design/transactions']
        del transactions['lists']
        self.db._database.save(transactions)
        # _get_generation()
        self.assertRaises(
            errors.MissingDesignDocListFunctionError,
            self.db._get_generation)
        # _get_generation_info()
        self.assertRaises(
            errors.MissingDesignDocListFunctionError,
            self.db._get_generation_info)
        # _get_trans_id_for_gen()
        self.assertRaises(
            errors.MissingDesignDocListFunctionError,
            self.db._get_trans_id_for_gen, 1)
        # whats_changed()
        self.assertRaises(
            errors.MissingDesignDocListFunctionError,
            self.db.whats_changed)

    def test_missing_design_doc_named_views_raises(self):
        """
        Test that all methods that access design documents' named views  will
        raise if the views are not present.
        """
        self.db = couch.CouchDatabase.open_database(
            urljoin('http://127.0.0.1:%d' % self.wrapper.port, 'test'),
            create=True,
            ensure_ddocs=True)
        # erase views from _design/docs
        docs = self.db._database['_design/docs']
        del docs['views']
        self.db._database.save(docs)
        # erase views from _design/syncs
        syncs = self.db._database['_design/syncs']
        del syncs['views']
        self.db._database.save(syncs)
        # erase views from _design/transactions
        transactions = self.db._database['_design/transactions']
        del transactions['views']
        self.db._database.save(transactions)
        # _get_generation()
        self.assertRaises(
            errors.MissingDesignDocNamedViewError,
            self.db._get_generation)
        # _get_generation_info()
        self.assertRaises(
            errors.MissingDesignDocNamedViewError,
            self.db._get_generation_info)
        # _get_trans_id_for_gen()
        self.assertRaises(
            errors.MissingDesignDocNamedViewError,
            self.db._get_trans_id_for_gen, 1)
        # _get_transaction_log()
        self.assertRaises(
            errors.MissingDesignDocNamedViewError,
            self.db._get_transaction_log)
        # whats_changed()
        self.assertRaises(
            errors.MissingDesignDocNamedViewError,
            self.db.whats_changed)

    def test_deleted_design_doc_raises(self):
        """
        Test that all methods that access design documents will raise if the
        design docs are not present.
        """
        self.db = couch.CouchDatabase.open_database(
            urljoin('http://127.0.0.1:%d' % self.wrapper.port, 'test'),
            create=True,
            ensure_ddocs=True)
        # delete _design/docs
        del self.db._database['_design/docs']
        # delete _design/syncs
        del self.db._database['_design/syncs']
        # delete _design/transactions
        del self.db._database['_design/transactions']
        # _get_generation()
        self.assertRaises(
            errors.MissingDesignDocDeletedError,
            self.db._get_generation)
        # _get_generation_info()
        self.assertRaises(
            errors.MissingDesignDocDeletedError,
            self.db._get_generation_info)
        # _get_trans_id_for_gen()
        self.assertRaises(
            errors.MissingDesignDocDeletedError,
            self.db._get_trans_id_for_gen, 1)
        # _get_transaction_log()
        self.assertRaises(
            errors.MissingDesignDocDeletedError,
            self.db._get_transaction_log)
        # whats_changed()
        self.assertRaises(
            errors.MissingDesignDocDeletedError,
            self.db.whats_changed)
