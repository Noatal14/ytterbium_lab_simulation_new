"""Threaded HTTP transport for the workflow API's numeric loopback interface."""

from http.server import ThreadingHTTPServer
from socketserver import TCPServer


class LoopbackThreadingHTTPServer(ThreadingHTTPServer):
    """Use the bound numeric address as HTTP metadata without reverse DNS.

    HTTPServer normally resolves server_name after binding and before listening.
    This bridge serves only 127.0.0.1, so no hostname lookup is needed. Keep the
    standard TCP bind options and ThreadingHTTPServer activation/lifecycle.
    """

    def server_bind(self) -> None:
        if self.server_address[0] != "127.0.0.1":
            raise ValueError("Workflow HTTP server requires numeric loopback 127.0.0.1.")
        TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]
