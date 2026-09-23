"""Сделать человека модератором — или снять роль.

Модератор — сотрудник в группе «Модератор» с правами из
`core/domain/moderation.MODERATOR_PERMISSIONS`. Руками это три места в
админке (флаг сотрудника, группа, права группы), и собранная руками
группа на каждой машине своя. Команда делает это одним движением и
заодно приводит группу к списку в коде.

Человек сначала входит на сайт через Telegram — аккаунт появляется на
анкете, — потом его ник передаётся сюда. Пароля команда не заводит:
модератор входит тем же Telegram, сессия одна на сайт и админку.

    manage.py make_moderator aidana
    manage.py make_moderator aidana --revoke
    manage.py make_moderator --list
"""

from django.core.management.base import CommandError

from core import data

from ._base import QuietCommand


class Command(QuietCommand):
    help = 'Выдаёт или снимает роль модератора; без ника с --list — список.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument('username', nargs='?',
                            help='Ник на портале (без @).')
        parser.add_argument('--revoke', action='store_true',
                            help='Снять роль, а не выдать.')
        parser.add_argument('--list', action='store_true',
                            help='Показать, кто сейчас модерирует.')

    def handle(self, *args, **options):
        if options['list']:
            # Группа приводится и здесь: список — повод заглянуть, и
            # заглянувший должен видеть права по нынешнему коду.
            data.moderator_group()
            names = [u.username for u in data.moderators()]
            self.say(options, 'moderators: ' + (', '.join(names) or 'none'))
            return

        username = (options['username'] or '').lstrip('@')
        if not username:
            raise CommandError('Ник керек: make_moderator <username>.')
        user = data.author_by_username(username)
        if user is None:
            raise CommandError(
                f'@{username} табылмады. Алдымен сайтқа Telegram арқылы '
                f'кіріп, анкетаны толтыруы керек.')

        if options['revoke']:
            data.revoke_moderator(user)
            self.say(options, f'@{username}: moderator role revoked')
        else:
            data.grant_moderator(user)
            self.say(options, f'@{username}: moderator role granted')
