#!/usr/bin/env python3
"""Mock Intel AMT WS-Man endpoint for testing ./amt16 without hardware.

Speaks just enough: TLS, HTTP Digest auth, Enumerate/Pull on
CIM_AssociatedPowerManagementService, RequestPowerStateChange and
ChangeBootOrder on CIM_BootConfigSetting.

Env:
  MOCK_STATE   power state returned by Pull (default 2)
  MOCK_DIRECT  if set, Enumerate returns the object inline (no Pull needed)
  MOCK_FAULT   if set, every invocation returns a SOAP Fault
  MOCK_REJECT  if set, always answer 401
  MOCK_404     if set, always answer 404
  MOCK_REQS    path of a file to append each request body to
"""
import base64
import hashlib
import os
import re
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = os.environ.get("MOCK_STATE", "2")
DIRECT = bool(os.environ.get("MOCK_DIRECT"))
FAULT = bool(os.environ.get("MOCK_FAULT"))
REQS = os.environ.get("MOCK_REQS", "/tmp/mock_amt.requests")

NS_S = "http://www.w3.org/2003/05/soap-envelope"
NS_A = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
NS_W = "http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"
NS_E = "http://schemas.xmlsoap.org/ws/2004/09/enumeration"
NS_APMS = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_AssociatedPowerManagementService"

NONCE = "deadbeefnonce"
REALM = "Digest:" + hashlib.md5(b"Intel(r) AMT").hexdigest().upper()


def envelope(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<s:Envelope xmlns:s="{NS_S}" xmlns:wsa="{NS_A}" xmlns:wsman="{NS_W}" '
        f'xmlns:wsen="{NS_E}" xmlns:h="{NS_APMS}"><s:Header>'
        f'<wsa:Action s:mustUnderstand="true">http://schemas.dmtf.org/wbem/wsman/1/wsman/IdentifyResponse</wsa:Action>'
        f'<wsa:MessageID>uuid:mock-reply</wsa:MessageID>'
        f'<wsa:RelatesTo>uuid:mock</wsa:RelatesTo></s:Header>'
        f"<s:Body>{body}</s:Body></s:Envelope>"
    ).encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, payload=b"", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", 'application/soap+xml;charset=UTF-8')
        self.send_header("Content-Length", str(len(payload)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n).decode("utf-8", "replace")

        if self.path != "/wsman":
            self._send(404, b"not found")
            return
        if os.environ.get("MOCK_REJECT"):
            self._send(401, b"", {"WWW-Authenticate": f'Digest realm="{REALM}", qop="auth", nonce="{NONCE}"'})
            return
        if os.environ.get("MOCK_404"):
            self._send(404, b"not found")
            return
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Digest "):
            self._send(
                401,
                b"",
                {"WWW-Authenticate": f'Digest realm="{REALM}", qop="auth", '
                                      f'nonce="{NONCE}", opaque="opaque", algorithm=MD5'},
            )
            return
        if 'response="' not in auth:
            self._send(401, b"")
            return

        with open(REQS, "a") as fh:
            fh.write(body + "\n=====\n")

        if self.headers.get("Content-Type", "") != "application/soap+xml;charset=UTF-8":
            self._send(415, envelope(
                '<s:Fault><s:Code><s:Value>s:Sender</s:Value></s:Code>'
                '<s:Reason><s:Text xml:lang="en">bad content type</s:Text></s:Reason></s:Fault>'))
            return

        if FAULT:
            self._send(200, envelope(
                '<s:Fault><s:Code><s:Value>s:Sender</s:Value><s:Subcode>'
                '<s:Value>wsa:ActionNotSupported</s:Value></s:Subcode></s:Code>'
                '<s:Reason><s:Text xml:lang="en">The intended resource does not exist</s:Text>'
                '</s:Reason></s:Fault>'))
            return

        if "RequestPowerStateChange_INPUT" in body:
            m = re.search(r"<n1:PowerState>(\d+)</n1:PowerState>", body)
            state = m.group(1) if m else "?"
            with open(REQS + ".power", "a") as fh:
                fh.write(state + "\n")
            self._send(200, envelope(
                '<h:RequestPowerStateChange_OUTPUT xmlns:h="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_PowerManagementService">'
                f'<h:ReturnValue>0</h:ReturnValue></h:RequestPowerStateChange_OUTPUT>'))
            return

        if "ChangeBootOrder_INPUT" in body:
            srcs = re.findall(r'InstanceID">([^<]+)<', body)
            src = srcs[-1] if srcs else None
            with open(REQS + ".boot", "a") as fh:
                fh.write((src if src else "?") + "\n")
            self._send(200, envelope(
                '<h:ChangeBootOrder_OUTPUT xmlns:h="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_BootConfigSetting">'
                '<h:ReturnValue>0</h:ReturnValue></h:ChangeBootOrder_OUTPUT>'))
            return

        instance = (
            f'<h:CIM_AssociatedPowerManagementService xmlns:h="{NS_APMS}">'
            f"<h:AvailableRequestedPowerStates>2</h:AvailableRequestedPowerStates>"
            f"<h:PowerState>{STATE}</h:PowerState>"
            f"<h:LastPowerStateChange>2026-11-17T10:00:00Z</h:LastPowerStateChange>"
            f"<h:ElementName>ManagedSystem</h:ElementName>"
            f"</h:CIM_AssociatedPowerManagementService>"
        )

        if "Enumerate" in body:
            if DIRECT:
                self._send(200, envelope(
                    f'<wsen:EnumerateResponse xmlns:wsen="{NS_E}"><wsen:Items>{instance}'
                    f"</wsen:Items></wsen:EnumerateResponse>"))
            else:
                self._send(200, envelope(
                    f'<wsen:EnumerateResponse xmlns:wsen="{NS_E}">'
                    f"<wsen:EnumerationContext>CTX-MOCK-1</wsen:EnumerationContext>"
                    f"</wsen:EnumerateResponse>"))
            return

        if "Pull" in body:
            ctx = re.search(r"EnumerationContext>([^<]*)<", body)
            if not ctx or ctx.group(1) != "CTX-MOCK-1":
                self._send(200, envelope(
                    '<s:Fault><s:Code><s:Value>s:Sender</s:Value></s:Code>'
                    '<s:Reason><s:Text xml:lang="en">invalid enumeration context</s:Text></s:Reason></s:Fault>'))
                return
            self._send(200, envelope(
                f'<wsen:PullResponse xmlns:wsen="{NS_E}"><wsen:Items>{instance}</wsen:Items>'
                f"<wsen:EndOfSequence/></wsen:PullResponse>"))
            return

        self._send(200, envelope(
            '<s:Fault><s:Code><s:Value>s:Sender</s:Value></s:Code>'
            '<s:Reason><s:Text xml:lang="en">unsupported action</s:Text></s:Reason></s:Fault>'))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 16993
    cert, key = sys.argv[2], sys.argv[3]
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f"mock AMT on https://127.0.0.1:{port}/wsman", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
