from allauth.account import signals as account_signals
from allauth.account.internal.flows.login_by_code import LoginCodeVerificationProcess
from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver

from core import audit


@receiver(account_signals.user_logged_in)
def on_login(sender, request, user, **kwargs):
    audit.record("auth.login", request=request, actor=user)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        audit.record("auth.logout", request=request, actor=user)


@receiver(account_signals.user_signed_up)
def on_signup(sender, request, user, **kwargs):
    audit.record("auth.signup", request=request, actor=user)


@receiver(account_signals.login_code_rejected, sender=LoginCodeVerificationProcess)
def on_code_rejected(sender, request, user, last_attempt=False, **kwargs):
    audit.record("auth.code_rejected", request=request, actor=user, last_attempt=bool(last_attempt))
