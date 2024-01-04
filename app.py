#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2020 Diego Elio Pettenò
#
# SPDX-License-Identifier: MIT

import dataclasses
import http
import os
import pathlib
import urllib
from typing import Self

import flask

_SOURCE_PATH = os.getenv("SERVE_SOURCE_PATH", "www")

app = flask.Flask(__name__, static_folder=_SOURCE_PATH)

_REDIRECT_STATUS_CODES = {
    http.HTTPStatus.MOVED_PERMANENTLY,
    http.HTTPStatus.FOUND,
    http.HTTPStatus.TEMPORARY_REDIRECT,
    http.HTTPStatus.PERMANENT_REDIRECT,
}


@dataclasses.dataclass
class Redirect:
    old_url: str
    new_url: str | None
    code: http.HTTPStatus = http.HTTPStatus.TEMPORARY_REDIRECT

    @classmethod
    def from_line(cls, line: str) -> Self:
        match line.split():
            case [old_url, "-", "410"] | [old_url, "-"]:
                return cls(old_url, None, http.HTTPStatus.GONE)
            case [_, _, "410"]:
                raise ValueError(
                    "GONE redirects require the second URL to be set to '-'"
                )
            case [old_url, new_url]:
                return cls(old_url, new_url)
            case [old_url, new_url, code]:
                status = http.HTTPStatus(int(code))
                if status not in _REDIRECT_STATUS_CODES:
                    raise ValueError(
                        f"Only redirect status code are allowed in {line=}"
                    )
                return cls(old_url, new_url, code=status)


def _get_all_redirects():
    all_redirects = {}

    with (pathlib.Path(_SOURCE_PATH) / "_redirects").open() as redirects:
        for line in redirects.readlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            redirect = Redirect.from_line(line)
            all_redirects[redirect.old_url] = redirect

    return all_redirects


@app.before_request
def before_request_handler():
    if "//" in flask.request.environ["RAW_URI"]:
        app.logger.warning(
            "Working around https://github.com/pallets/werkzeug/issues/491"
        )
        # We need to add a localhost entry otherwise it considers the first component a hostname!
        parsed_url = urllib.parse.urlparse(
            "http://localhost" + flask.request.environ["RAW_URI"]
        )
        flask.request.path = parsed_url.path
        flask.request.environ["PATH_INFO"] = parsed_url.path


@app.route("/")
def root():
    return catch_all("/")


@app.route("/<path:path>")
def catch_all(path):
    # Ignore the path due to https://github.com/pallets/werkzeug/issues/491
    path = flask.request.path.lower()

    # Normalize the path, because we can't rely on Flask's normalization
    path = path.replace("//", "/")

    app.logger.debug("Looking for a replacement for %s", path)

    redirect = _get_all_redirects().get(path)
    if redirect is None:
        return flask.abort(http.HTTPStatus.NOT_FOUND)

    if redirect.code in _REDIRECT_STATUS_CODES:
        return flask.redirect(redirect.new_url)

    return flask.abort(redirect.code)
