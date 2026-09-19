"""Доставка уведомлений в Telegram: очередь и выключатель.

`Notification.pushed_at` — очередь отправки: «неотправленное» это строки
без отметки, и отдельной таблицы под них не нужно.
`User.telegram_push` — слать ли вообще; снимает его и сам человек, и
платформа, когда бот получил отказ навсегда.

`gender` здесь **не по теме**: подписи в справочнике менялись
(«Ұл» → «Ұл/Ер») без миграции, и состояние разошлось с моделью ещё
тогда. Правка только состояния, SQL не выполняется; лежит здесь потому,
что `makemigrations` сносит расхождение в первую же миграцию, а
заводить вторую ради строки choices незачем. Ловить такое должен
`makemigrations --check` в непрерывной интеграции — её пока нет.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_pen_name_only'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='pushed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Telegram-ға жіберілді'),
        ),
        migrations.AddField(
            model_name='user',
            name='telegram_push',
            field=models.BooleanField(default=True, verbose_name='Telegram-хабарлама'),
        ),
        migrations.AlterField(
            model_name='user',
            name='gender',
            field=models.CharField(blank=True, choices=[('boy', 'Ұл/Ер'), ('girl', 'Қыз/Әйел')], max_length=4, verbose_name='жынысы'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(condition=models.Q(('pushed_at__isnull', True)), fields=['created_at'], name='notif_unpushed'),
        ),
    ]
