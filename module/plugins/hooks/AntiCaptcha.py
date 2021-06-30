# -*- coding: utf-8 -*-

import base64
import time
import urlparse

from ..internal.Addon import Addon
from ..internal.misc import json, threaded, fs_encode


class AntiCaptcha(Addon):
    __name__ = "AntiCaptcha"
    __type__ = "hook"
    __version__ = "0.01"
    __status__ = "testing"

    __config__ = [("activated", "bool", "Activated", False),
                  ("check_client", "bool", "Don't use if client is connected", True),
                  ("solve_image", "bool", "Solve image catcha", True),
                  ("solve_recaptcha", "bool", "Solve ReCaptcha", True),
                  ("solve_hcaptcha", "bool", "Solve HCaptcha", True),
                  ("refund", "bool", "Request refund if result incorrect", False),
                  ("passkey", "password", "API key", ""),
                  ("timeout", "int", "Timeout in seconds (min 60, max 3999)", "900")]

    __description__ = """Send captchas to anti-captcha.com"""
    __license__ = "GPLv3"
    __authors__ = [("GammaC0de", "nitzo2001[AT]yahho[DOT]com")]

    TASK_TYPES = {
        "ReCaptcha": "RecaptchaV2TaskProxyless",
        "HCaptcha": "HCaptchaTaskProxyless",
    }

    # See https://anti-captcha.com/apidoc
    API_URL = "https://api.anti-captcha.com/"

    def api_request(self, method, post):
        json_data = self.load(self.API_URL + method, post=json.dumps(post))
        return json.loads(json_data)

    def get_credits(self):
        credits = self.db.retrieve("credits", {"balance": 0, "time": 0})

        #: Docs says: "Please don't call this method more often than once in 30 seconds"
        if time.time() - credits["time"] >= 30:
            api_data = self.api_request(
                "getBalance", {"clientKey": self.config.get("passkey")}
            )
            if api_data["errorId"] != 0:
                self.log_error(_("API error"), api_data["errorDescription"])
                return 0

            credits = {"balance": api_data["balance"], "time": time.time()}
            self.db.store("credits", credits)

        balance = credits["balance"]
        self.log_info(_("Credits left: %.2f$") % balance)

        return balance

    @threaded
    def _process_captcha(self, task):
        url_p = urlparse.urlparse(task.captchaParams["url"])
        if task.isInteractive():
            if url_p.scheme not in ("http", "https"):
                self.log_error(_("Invalid url"))
                return

            api_data = self.api_request(
                "createTask",
                {
                    "clientKey": self.config.get("passkey"),
                    "softId": 976,
                    "task": {
                        "type": self.TASK_TYPES[task.captchaParams["captcha_plugin"]],
                        "websiteURL": r"%s://%s/" % (url_p.scheme, url_p.netloc),
                        "websiteKey": task.captchaParams["sitekey"],
                    },
                },
            )
        else:
            try:
                with open(fs_encode(task.captchaParams["file"], "rb")) as fp:
                    data = fp.read()

            except IOError as exc:
                self.log_error(exc)
                return

            api_data = self.api_request(
                "createTask",
                {
                    "clientKey": self.config.get("passkey"),
                    "softId": 976,
                    "task": {
                        "type": "ImageToTextTask",
                        "body": base64.b64encode(data),
                        "case": True,
                        "websiteURL": r"%s://%s/" % (url_p.scheme, url_p.netloc),
                    },
                },
            )
        if api_data["errorId"] != 0:
            task.error = api_data["errorDescription"]
            self.log_error(_("API error"), api_data["errorDescription"])
            return

        ticket = api_data["taskId"]
        self.log_debug("NewCaptchaID ticket: %s" % ticket, task.captchaParams.get("file", ""))

        task.data["ticket"] = ticket

        result = None
        for i in range(int(self.config.get("timeout") / 5)):
            api_data = self.api_request(
                "getTaskResult",
                {"clientKey": self.config.get("passkey"), "taskId": ticket},
            )
            if api_data["errorId"] != 0:
                task.error = api_data["errorDescription"]
                self.log_error(_("API error"), api_data["errorDescription"])
                break

            if api_data["status"] == "processing":
                time.sleep(5)
            else:
                captcha_plugin = task.captchaParams["captcha_plugin"]
                if captcha_plugin in ("HCaptcha", "ReCaptcha"):
                    result = api_data["solution"]["gRecaptchaResponse"]

                elif task.isTextual():
                    result = api_data["solution"]["text"]

                break

        else:
            self.log_debug("Could not get result: %s" % ticket)

        self.log_info(_("Captcha result for ticket %s: %s") % (ticket, result))

        task.setResult(result)

    def captcha_task(self, task):
        if task.isInteractive():
            captcha_plugin = task.captchaParams["captcha_plugin"]
            if captcha_plugin == "ReCaptcha" and not self.config.get("solve_recaptcha"):
                return
            elif captcha_plugin == "HCaptcha" and not self.config.get("solve_hcaptcha"):
                return

        else:
            if not task.isTextual():
                return
            elif not self.config.get("solve_image"):
                return

        if not self.config.get("passkey"):
            return

        if self.pyload.isClientConnected() and self.config.get("check_client"):
            return

        credits = self.get_credits()
        if credits < 0.05:
            self.log_error(_("Your captcha anti-captcha.com account has not enough credits"))
            return

        timeout = min(max(self.config.get("timeout"), 300), 3999)
        task.handler.append(self)
        task.setWaiting(timeout)

        self._process_captcha(task)

    def _captcha_response(self, task, correct):
        request_type = "correct" if correct else "refund"

        if "ticket" not in task.data:
            self.log_debug("No CaptchaID for %s request (task: %s)" % (request_type, task))
            return

        if not self.config.get("refund", False) or correct:
            return

        if task.captchaParams["captcha_plugin"] == "ReCaptcha":
            method = "reportIncorrectRecaptcha"
        elif task.isTextual():
            method = "reportIncorrectImageCaptcha"
        else:
            return

        for _ in range(3):
            api_data = self.api_request(
                method,
                {
                    "clientKey": self.config.get("passkey"),
                    "taskId": task.data["ticket"],
                },
            )

            self.log_debug("Request %s: %s" %(request_type, api_data))
            if api_data["errorId"] == 0:
                break
            time.sleep(5)
        else:
            self.log_debug("Could not send %s request: %s" % (request_type, api_data["errorDescription"]))

    def captcha_correct(self, task):
        self._captcha_response(task, True)

    def captcha_invalid(self, task):
        self._captcha_response(task, False)
