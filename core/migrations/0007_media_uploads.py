"""Обложка, афиша и эмблема становятся загружаемыми файлами (DEC-23, BR-46).

Колонка та же — `varchar` с путём относительно `MEDIA_ROOT`, — меняется
только то, как путь туда попадает: раньше его вписывали строкой, а файл
клали на диск мимо приложения. Инструмент модерации в MVP один (DEC-23),
и «загрузить эмблему награды» обязано делаться в нём.

Данные не трогаем: значения сида — те же относительные пути, и после
`AlterField` они читаются как прежде.
"""

import core.models
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_tag_usage_count_tag_weekly_count'),
    ]

    operations = [
        migrations.AlterField(
            model_name='contest',
            name='poster',
            field=models.FileField(blank=True, max_length=200, upload_to=core.models.contest_poster_path, validators=[django.core.validators.FileExtensionValidator(['png', 'jpg', 'jpeg', 'webp'], message='Тек растр сурет: png, jpg, webp. SVG қабылданбайды (BR-46).')], verbose_name='афиша'),
        ),
        migrations.AlterField(
            model_name='contestaward',
            name='image',
            field=models.FileField(blank=True, max_length=200, upload_to=core.models.award_image_path, validators=[django.core.validators.FileExtensionValidator(['png', 'jpg', 'jpeg', 'webp'], message='Тек растр сурет: png, jpg, webp. SVG қабылданбайды (BR-46).')], verbose_name='эмблема'),
        ),
        migrations.AlterField(
            model_name='story',
            name='cover',
            field=models.FileField(blank=True, max_length=200, upload_to=core.models.story_cover_path, validators=[django.core.validators.FileExtensionValidator(['png', 'jpg', 'jpeg', 'webp'], message='Тек растр сурет: png, jpg, webp. SVG қабылданбайды (BR-46).')], verbose_name='мұқаба'),
        ),
    ]
