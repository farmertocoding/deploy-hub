"""Entry: python -m intake. Binds loopback; live public intake is Joseph."""
from wsgiref.simple_server import make_server

from intake.app import application


def main():
    make_server("127.0.0.1", 8080, application).serve_forever()


if __name__ == "__main__":
    main()
