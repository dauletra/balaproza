"""Число частей перестаёт храниться (PLAN-OPTIMIZATION, шаг 1.2).

Колонку объявлял автор при создании работы, а `save_chapter` её не
обновлял: работа с пятью написанными главами показывала «0 бөлім».
Теперь число считается по записям глав — аннотацией `chapter_count`
в выдаче и `chapter_set.count()` у одиночного объекта.

Данные не переносятся: колонка расходилась с текстом, и переносить
разошедшееся некуда. У четырёх сериалов демо-корпуса, обещавших части
без текста, счётчик станет нулевым — это и есть их настоящее состояние.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_user_profile_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='story',
            name='chapters',
        ),
    ]
