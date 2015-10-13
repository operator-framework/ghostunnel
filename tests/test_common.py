from subprocess import call
from OpenSSL import crypto
import SocketServer, threading, time, socket, ssl, os

LOCALHOST = '127.0.0.1'

# Helper function to create a signed cert
def create_signed_cert(ou, root):
  call("openssl genrsa -out {0}.key 1024".format(ou), shell=True)
  call("openssl req -new -key {0}.key -out {0}.csr -subj /C=US/ST=CA/O=ghostunnel/OU={0}".format(ou), shell=True)
  call("chmod 600 {0}.key".format(ou), shell=True)
  call("openssl x509 -req -in {0}.csr -CA {1}.crt -CAkey {1}.key -CAcreateserial -out {0}.crt -days 5 -extfile openssl.ext".format(ou, root), shell=True)
  call("openssl pkcs12 -export -out {0}.p12 -in {0}.crt -inkey {0}.key -password pass:".format(ou), shell=True)

# Helper function to create a root cert
def create_root_cert(root):
  call('openssl genrsa -out {0}.key 1024'.format(root), shell=True)
  call('openssl req -x509 -new -key {0}.key -days 5 -out {0}.crt -subj /C=US/ST=CA/O=ghostunnel/OU={0}'.format(root), shell=True)
  call('chmod 600 {0}.key'.format(root), shell=True)

def cleanup_certs(names):
  for name in names:
    for ext in ["crt", "key", "csr", "srl", "p12"]:
      try:
        os.remove('{0}.{1}'.format(name, ext))
      except OSError:
        pass

def print_ok(msg):
  print "\033[92m{0}\033[0m".format(msg)

def connect_until_expected_serial(client, server, port):
  p12 = crypto.load_pkcs12(file("{0}.p12".format(server), 'rb').read())
  expected_serial = p12.get_certificate().get_serial_number()
  for i in range(1, 5):
    try:
      # TODO: time.sleep(1) shouldn't be needed.
      time.sleep(1)
      c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      c.settimeout(1)
      client_sock = ssl.wrap_socket(c, keyfile="{0}.key".format(client),
        certfile="{0}.crt".format(client), ssl_version=ssl.PROTOCOL_TLSv1_2,
        cert_reqs=ssl.CERT_REQUIRED, ca_certs='root.crt')
      client_sock.connect((LOCALHOST, port))

      if (int(client_sock.getpeercert()['serialNumber'], 16) == expected_serial):
        print_ok("got expected serial")
        return client_sock
      time.sleep(1)
    except Exception as e:
      time.sleep(1)
      pass
  raise Exception("ghostunnel did not pick new cert?")

# This is whacky but works. This class represents a pair of sockets which
# correspond to each end of the tunnel. The class lets you verify that sending
# data in one socket shows up on the other. It also allows testing that closing
# one socket closes the other.
class SocketPair:
  def __init__(self, client, server, client_port, server_port):
    # setup a listening socket
    l = None
    try:
      l = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      l.settimeout(1)
      l.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      l.bind((LOCALHOST, server_port))
      l.listen(1)

      # setup client socket, keep waiting until we get the expected serial
      self.client_sock = connect_until_expected_serial(client, server, client_port)

      # grab the server socket
      self.server_sock, _ = l.accept()
      self.server_sock.settimeout(10)
    finally:
      l.close()

  def validate_tunnel_ou(self, string, msg):
    if self.client_sock.getpeercert()['subject'][3][0][1] != string:
      raise Exception("did not connect to expected peer: ", self.client_sock.getpeercert())
    print_ok(msg)

  def validate_can_send_from_client(self, string, msg):
    self.client_sock.send(string)
    data = self.server_sock.recv(len(string))
    if data != string:
      raise Exception("did not receive expected string.")
    print_ok(msg)

  def validate_can_send_from_server(self, string, msg):
    self.server_sock.send(string)
    data = self.client_sock.recv(len(string))
    if data != string:
      raise Exception("did not receive expected string")
    print_ok(msg)

  def validate_closing_client_closes_server(self, msg):
    self.client_sock.shutdown(socket.SHUT_RDWR)
    self.client_sock.close()
    # if the tunnel doesn't close the connection, recv(1) will raise a Timeout
    self.server_sock.recv(1)
    print_ok(msg)

  def validate_closing_server_closes_client(self, msg):
    self.server_sock.shutdown(socket.SHUT_RDWR)
    self.server_sock.close()
    # if the tunnel doesn't close the connection, recv(1) will raise a Timeout
    self.client_sock.recv(1)
    print_ok(msg)

# Like SocketPair, but uses UNIX sockets for the backend
class SocketPairUnix(SocketPair):
  def __init__(self, client, client_port, socket_path):
    # setup a listening socket
    l = None
    try:
      l = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
      l.settimeout(1)
      l.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      l.bind(socket_path)
      l.listen(1)

      # setup the client socket
      # TODO: figure out a way to know when the server is ready?
      time.sleep(1)
      c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      c.settimeout(1)
      self.client_sock = ssl.wrap_socket(c, keyfile='{0}.key'.format(client),
        certfile='{0}.crt'.format(client), ssl_version=ssl.PROTOCOL_TLSv1_2,
        cert_reqs=ssl.CERT_REQUIRED, ca_certs='root.crt')
      self.client_sock.connect((LOCALHOST, client_port))

      # grab the server socket
      self.server_sock, _ = l.accept()
      self.server_sock.settimeout(1)
    finally:
      l.close()