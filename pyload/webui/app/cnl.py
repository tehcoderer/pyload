# -*- coding: utf-8 -*-

from __future__ import with_statement

import base64
import os
import re
import urllib

from binascii import unhexlify

from bottle import route, request, HTTPError

from pyload.webui import PYLOAD, DL_ROOT, JS


try:
    from Crypto.Cipher import AES
except Exception:
    pass


def local_check(function):


    def _view(*args, **kwargs):
        if request.environ.get("REMOTE_ADDR", "0") in ("127.0.0.1", "localhost") \
           or request.environ.get("HTTP_HOST", "0") in ("127.0.0.1:9666", "localhost:9666"):
            return function(*args, **kwargs)
        else:
            return HTTPError(403, "Forbidden")

    return _view


@route('/flash')
@route('/flash/<id>')
@route('/flash', method='POST')
@local_check
def flash(id="0"):
    return "JDownloader\r\n"


@route('/flash/add', method='POST')
@local_check
def add(request):
    package = request.POST.get('referer', None)
    urls = filter(lambda x: x != "", request.POST['urls'].split("\n"))

    if package:
        PYLOAD.addPackage(package, urls, 0)
    else:
        PYLOAD.generateAndAddPackages(urls, 0)

    return ""


@route('/flash/addcrypted', method='POST')
@local_check
def addcrypted():
    package = request.forms.get('referer', 'ClickNLoad Package')
    dlc = request.forms['crypted'].replace(" ", "+")

    dlc_path = os.path.join(DL_ROOT, package.replace("/", "").replace("\\", "").replace(":", "") + ".dlc")
    with open(dlc_path, "wb") as dlc_file:
        dlc_file.write(dlc)

    try:
        PYLOAD.addPackage(package, [dlc_path], 0)
    except Exception:
        return HTTPError()
    else:
        return "success\r\n"


@route('/flash/addcrypted2', method='POST')
@local_check
def addcrypted2():
    package = request.forms.get("source", None)
    crypted = request.forms['crypted']
    jk = request.forms['jk']

    crypted = base64.standard_b64decode(urllib.unquote(crypted.replace(" ", "+")))
    if JS:
        jk = "%s f()" % jk
        jk = JS.eval(jk)

    else:
        try:
            jk = re.findall(r"return ('|\")(.+)('|\")", jk)[0][1]
        except Exception:
            # Test for some known js functions to decode
            if jk.find("dec") > -1 and jk.find("org") > -1:
                org = re.findall(r"var org = ('|\")([^\"']+)", jk)[0][1]
                jk = list(org)
                jk.reverse()
                jk = "".join(jk)
            else:
                print "Could not decrypt key, please install py-spidermonkey or ossp-js"

    try:
        Key = unhexlify(jk)
    except Exception:
        print "Could not decrypt key, please install py-spidermonkey or ossp-js"
        return "failed"

    IV = Key

    obj = AES.new(Key, AES.MODE_CBC, IV)
    result = obj.decrypt(crypted).replace("\x00", "").replace("\r", "").split("\n")

    result = filter(lambda x: x != "", result)

    try:
        if package:
            PYLOAD.addPackage(package, result, 0)
        else:
            PYLOAD.generateAndAddPackages(result, 0)
    except Exception:
        return "failed can't add"
    else:
        return "success\r\n"


@route('/flashgot_pyload')
@route('/flashgot_pyload', method='POST')
@route('/flashgot')
@route('/flashgot', method='POST')
@local_check
def flashgot():
    if request.environ['HTTP_REFERER'] not in ("http://localhost:9666/flashgot", "http://127.0.0.1:9666/flashgot"):
        return HTTPError()

    autostart = int(request.forms.get('autostart', 0))
    package = request.forms.get('package', None)
    urls = filter(lambda x: x != "", request.forms['urls'].split("\n"))
    folder = request.forms.get('dir', None)

    if package:
        PYLOAD.addPackage(package, urls, autostart)
    else:
        PYLOAD.generateAndAddPackages(urls, autostart)

    return ""


@route('/crossdomain.xml')
@local_check
def crossdomain():
    rep = "<?xml version=\"1.0\"?>\n"
    rep += "<!DOCTYPE cross-domain-policy SYSTEM \"http://www.macromedia.com/xml/dtds/cross-domain-policy.dtd\">\n"
    rep += "<cross-domain-policy>\n"
    rep += "<allow-access-from domain=\"*\" />\n"
    rep += "</cross-domain-policy>"
    return rep


@route('/flash/checkSupportForUrl')
@local_check
def checksupport():
    url = request.GET.get("url")
    res = PYLOAD.checkURLs([url])
    supported = (not res[0][1] is None)

    return str(supported).lower()


@route('/jdcheck.js')
@local_check
def jdcheck():
    rep = "jdownloader=true;\n"
    rep += "var version='9.581;'"
    return rep