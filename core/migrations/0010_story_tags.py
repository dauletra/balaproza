import django.db.models.deletion
from django.db import migrations, models


def _copy_tag_links(apps, schema_editor):
    """Перенос существующей связки «работа-тег» в StoryTag.

    Момент, когда автор поставил тег, нигде не хранился, и `created_at`
    приближён датой создания работы. Идёт ДО смены источника `Story.tags`
    ниже — иначе читал бы уже несуществующую m2m-таблицу.
    """
    Story = apps.get_model('core', 'Story')
    StoryTag = apps.get_model('core', 'StoryTag')
    links = [
        StoryTag(story_id=story.pk, tag_id=tag.pk, created_at=story.created_at)
        for story in Story.objects.prefetch_related('tags').all()
        for tag in story.tags.all()
    ]
    StoryTag.objects.bulk_create(links)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_search_trigrams'),
    ]

    operations = [
        migrations.CreateModel(
            name='StoryTag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='қосылған')),
                ('story', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.story', verbose_name='шығарма')),
                ('tag', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.tag', verbose_name='тег')),
            ],
            options={
                'verbose_name': 'жұмыс тегі',
                'verbose_name_plural': 'жұмыс тегтері',
            },
        ),
        migrations.AddConstraint(
            model_name='storytag',
            constraint=models.UniqueConstraint(fields=('story', 'tag'), name='unique_tag_per_story'),
        ),
        migrations.RunPython(_copy_tag_links, migrations.RunPython.noop),
        # AlterField с through= напрямую Django не умеет («cannot alter to
        # or from M2M fields, or add or remove through= on M2M fields»).
        # Разделяем: в базе удаляется только старая авто-таблица m2m
        # (новая StoryTag уже создана и заполнена операцией выше), а
        # состояние ORM меняется отдельно, без второго SQL-действия —
        # таблица под него уже есть.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RemoveField(model_name='story', name='tags'),
            ],
            state_operations=[
                migrations.RemoveField(model_name='story', name='tags'),
                migrations.AddField(
                    model_name='story',
                    name='tags',
                    field=models.ManyToManyField(blank=True, related_name='stories',
                                                 through='core.StoryTag', to='core.tag',
                                                 verbose_name='тегтер'),
                ),
            ],
        ),
    ]
