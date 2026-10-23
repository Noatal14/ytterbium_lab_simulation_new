"""Disconnects affect response transmission only, never operation outcomes."""
import json
import os
import socket
import struct
import threading
from http.client import HTTPConnection
from types import SimpleNamespace

import pytest

from workflow_api.loopback_http import LoopbackThreadingHTTPServer
from workflow_api.server import WorkflowHandler


@pytest.mark.parametrize('error',[BrokenPipeError,ConnectionResetError,ConnectionAbortedError])
@pytest.mark.parametrize('where',['response','header','headers_end','body'])
def test_expected_disconnect_at_response_write_is_not_retried(error,where):
    handler=object.__new__(WorkflowHandler)
    handler.command='GET';calls=[]
    def emit(name):
        def call(*args):
            calls.append(name)
            if name==where:raise error('client disconnected')
        return call
    handler.send_response=emit('response');handler.send_header=emit('header');handler.end_headers=emit('headers_end');handler.wfile=SimpleNamespace(write=emit('body'))
    handler._json({'data':'real'},extra_headers={'X-Test':'real'})
    assert handler.close_connection is True
    assert calls.count('response')==1
    assert calls.count(where)==1
    assert calls[-1]==where


@pytest.mark.parametrize('error',[RuntimeError,OSError])
@pytest.mark.parametrize('where',['header','body'])
def test_unexpected_write_errors_propagate(error,where):
    handler=object.__new__(WorkflowHandler);handler.command='GET'
    def fail(*_):raise error('unexpected')
    handler.send_response=lambda *_:None;handler.send_header=fail if where=='header'else lambda *_:None;handler.end_headers=lambda:None;handler.wfile=SimpleNamespace(write=fail)
    with pytest.raises(error,match='unexpected'):handler._json({'data':'real'})


def test_serialization_failure_is_outside_disconnect_handling():
    handler=object.__new__(WorkflowHandler);handler.command='GET'
    handler.send_response=lambda *_:pytest.fail('no response before JSON serialization')
    with pytest.raises(TypeError):handler._json({'data':object()})


def test_actual_client_reset_then_health_json_succeeds():
    arrived=threading.Event();release=threading.Event();finished=threading.Event();errors=[]
    class Handler(WorkflowHandler):
        def do_GET(self):
            if self.path=='/abort-response':
                arrived.set()
                if not release.wait(3):raise RuntimeError('test release timed out')
                try:self._json({'data':'x'*(4*1024*1024)})
                finally:finished.set()
            else:super().do_GET()
    class Server(LoopbackThreadingHTTPServer):
        def handle_error(self,*_):
            import sys
            errors.append(sys.exc_info()[1])
    with Server(('127.0.0.1',0),Handler)as server:
        worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':0.02},daemon=True);worker.start()
        try:
            with socket.create_connection(server.server_address,timeout=2)as client:
                client.sendall(b'GET /abort-response HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
                assert arrived.wait(2)
                # Windows linger uses two unsigned shorts; POSIX uses two ints.
                client.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack('hh'if os.name=='nt'else'ii',1,0))
            release.set();assert finished.wait(3)
            connection=HTTPConnection(*server.server_address,timeout=2)
            try:
                connection.request('GET','/api/health');response=connection.getresponse();raw=response.read()
                assert response.status==200
                assert json.loads(raw)=={'api_version':1,'status':'ok'}
                assert response.getheader('Content-Type')=='application/json; charset=utf-8'
            finally:connection.close()
            assert errors==[]
        finally:
            release.set();server.shutdown();worker.join(3);assert not worker.is_alive()

@pytest.mark.parametrize('error',[BrokenPipeError,ConnectionResetError,ConnectionAbortedError])
def test_same_exception_from_serialization_still_propagates(monkeypatch,error):
    import workflow_api.server as module
    handler=object.__new__(WorkflowHandler);handler.command='GET'
    handler.send_response=lambda *_:pytest.fail('serialization must precede network writes')
    def fail(*_args,**_kwargs):raise error('not a transport write')
    monkeypatch.setattr(module.json,'dumps',fail)
    with pytest.raises(error,match='not a transport write'):handler._json({'data':'real'})
