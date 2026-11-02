"""Login, logout and the account page. Every other page needs a login."""

import sqlite3
import time
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from app import auth
from app.branding import APP_SLUG
from app.config import Env
from app.web.deps import get_db, render

router = APIRouter()

COOKIE = f"{APP_SLUG}_session"
FAILED_LOGIN_DELAY = 1


class LoginRequired(Exception):
    pass


def setup_admin(conn: sqlite3.Connection, env: Env) -> str | None:
    """Make the admin account from the environment when there is none. Returns what is missing, if anything."""
    if auth.get_admin(conn) is not None:
        return None
    missing = [name for name, value in (("ADMIN_USERNAME", env.admin_username), ("ADMIN_PASSWORD", env.admin_password))
               if not value]
    if missing:
        return f"Set {' and '.join(missing)} in the container's environment, then restart it."
    problem = auth.password_problem(env.admin_password)
    if problem:
        return f"ADMIN_PASSWORD is too short: {problem.lower()} Change it, then restart the container."
    auth.save_admin(conn, env.admin_username, env.admin_password)
    return None


def _check_origin(request: Request) -> None:
    """Forms of this app only: a page on another site can't post here with the session cookie."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Request from another site refused.")


def require_login(request: Request, db: sqlite3.Connection = Depends(get_db)) -> auth.User:
    _check_origin(request)
    user = auth.session_user(db, request.cookies.get(COOKIE))
    if user is None:
        raise LoginRequired()
    request.state.user = user
    return user


def login_redirect(request: Request, exc: LoginRequired) -> Response:
    target = f"/login?next={quote(request.url.path)}" if request.url.path != "/" else "/login"
    if request.headers.get("hx-request"):
        return Response(status_code=200, headers={"HX-Redirect": target})  # a fragment can't redirect the page
    return RedirectResponse(target, status_code=303)


def _safe_next(target: str) -> str:
    return target if target.startswith("/") and not target.startswith("//") else "/"


def _address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/login")
def login_page(request: Request, next: str = "/", db: sqlite3.Connection = Depends(get_db)):
    if auth.session_user(db, request.cookies.get(COOKIE)):
        return RedirectResponse(_safe_next(next), status_code=303)
    return render(request, "auth/login.html", next=_safe_next(next), setup_error=request.app.state.setup_error)


@router.post("/login")
def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
    db: sqlite3.Connection = Depends(get_db),
):
    _check_origin(request)
    context = {"next": _safe_next(next), "username": username, "setup_error": request.app.state.setup_error}
    throttle: auth.Throttle = request.app.state.throttle
    wait = throttle.wait(_address(request))
    if wait:
        return render(request, "auth/login.html", error=f"Too many wrong passwords. Try again in {wait // 60 + 1} min.",
                      **context)
    user = auth.check_login(db, username.strip(), password)
    if user is None:
        throttle.failed(_address(request))
        time.sleep(FAILED_LOGIN_DELAY)
        return render(request, "auth/login.html", error="Wrong username or password.", **context)
    throttle.succeeded(_address(request))
    response = RedirectResponse(context["next"], status_code=303)
    _set_cookie(request, response, auth.start_session(db, user))
    return response


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")


@router.post("/logout")
def logout(request: Request, db: sqlite3.Connection = Depends(get_db)):
    _check_origin(request)
    auth.end_sessions(db, request.cookies.get(COOKIE))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response


account = APIRouter(dependencies=[Depends(require_login)])


@account.get("/settings/account")
def account_page(request: Request):
    return render(request, "settings/account.html", active="settings", page="settings/account",
                  username=request.state.user.username)


@account.post("/settings/account")
def save_account(
    request: Request,
    username: str = Form(""),
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    db: sqlite3.Connection = Depends(get_db),
):
    user = request.state.user
    username = username.strip()

    def page(error=None, saved=False):
        return render(request, "partials/account_form.html", username=username or user.username, error=error,
                      saved=saved)

    if not username:
        return page("Enter a username.")
    if auth.check_login(db, user.username, current_password) is None:
        return page("The current password is wrong.")
    if new_password or confirm_password:
        if new_password != confirm_password:
            return page("The new passwords don't match.")
        problem = auth.password_problem(new_password)
        if problem:
            return page(problem)
    auth.save_admin(db, username, new_password or None)
    if new_password:
        auth.end_sessions(db, keep=request.cookies.get(COOKIE))  # sign out everywhere else
    return page(saved=True)
