"""Dev aid: mock of the bridge's POST /v1/chat.

Serves ui/ and answers /api/sam/chat, cycling through every `state` the real
bridge can return, so the customer surface can be looked at WITHOUT the agent
image, Atlassian credentials, or Docker.

    python3 ui/dev-mock.py      then open http://127.0.0.1:8099/customer/

Not part of any deployment. It exists because a UI whose states you have never
seen rendered is a UI you are guessing about -- `kb_unreachable` in particular
has to look nothing like `unknown`, and that is only checkable by looking.
"""
import http.server, json, os, socketserver, urllib.parse
ROOT = os.path.expanduser("~/rgsplus/repo/ui")
CITE = [{"title":"Objecten beheren","url":"https://rgsplus.atlassian.net/wiki/spaces/HELP/pages/1",
         "space":"HELP","excerpt":"Dubbelklik op de statuskolom om de status te wisselen."}]
SEQ = [
 {"state":"answer","reply":"Je kunt de status wisselen door te dubbelklikken op de statuskolom.","citations":CITE},
 {"state":"answer","reply":"Dat kan waarschijnlijk via het actiemenu.","citations":[]},
 {"state":"clarify","reply":"Gaat dit over de webversie of de inspectie-app? En om welk complex gaat het?"},
 {"state":"partial","reply":"Het exporteren van een scenario naar Excel staat beschreven in de handleiding.",
  "citations":CITE,"draft":{"summary":"Import scenario met meerdere valuta's mislukt",
  "description":"Vraag van de klant:\n\"Ik krijg mijn import niet voor elkaar\"\n\nGezocht op: scenario import excel, maatregel export.\nNiet gedocumenteerd: gedrag bij afwijkende decimalen.","draft_id":"2026-08-28-import.json"}},
 {"state":"unknown","reply":"Hier staat niets over in de handleiding. Ik zet je vraag door naar een collega.",
  "draft":{"summary":"Garantieverklaring genereren vanuit RGS+","description":"Klant vraagt of een garantieverklaring als formulier kan worden gegenereerd."}},
 {"state":"kb_unreachable","reply":""},
 {"state":"refuse","reply":"Vragen over je licentie of facturatie kan ik niet beantwoorden. Je contactpersoon bij RGS+ helpt je hiermee verder."},
 {"state":"safety","reply":""},
]
class H(http.server.SimpleHTTPRequestHandler):
    i = 0
    def __init__(self,*a,**k): super().__init__(*a,directory=ROOT,**k)
    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/api/sam/chat": return self.send_error(404)
        self.rfile.read(int(self.headers.get("Content-Length",0)))
        d = dict(SEQ[H.i % len(SEQ)]); H.i += 1
        d["session_id"]="mock-1"; d.setdefault("citations",[]); d.setdefault("draft",None)
        b=json.dumps(d).encode()
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass
socketserver.TCPServer.allow_reuse_address=True
with socketserver.TCPServer(("127.0.0.1",8099),H) as s: s.serve_forever()
