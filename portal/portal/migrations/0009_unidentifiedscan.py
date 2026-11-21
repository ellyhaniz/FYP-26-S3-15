import django.db.models.deletion
import django.utils.timezone
import portal.storage
from django.conf import settings
from django.db import migrations, models

FEATURE = "unidentified-scans"
TITLE = "Unidentified Scans"
ROLES = ["Researcher", "System Admin"]


def add_feature(apps, schema_editor):
    """Create the new portal section and give it to the roles that review scans.
    Only touches the profile types that already exist; nothing else is changed."""
    Feature = apps.get_model("portal", "Feature")
    ProfileType = apps.get_model("portal", "ProfileType")
    feature, _ = Feature.objects.get_or_create(code=FEATURE, defaults={"title": TITLE})
    for pt in ProfileType.objects.filter(group__name__in=ROLES):
        pt.permissions.add(feature)


def remove_feature(apps, schema_editor):
    apps.get_model("portal", "Feature").objects.filter(code=FEATURE).delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('portal', '0008_record_photos_in_database'),
    ]

    operations = [
        migrations.CreateModel(
            name='UnidentifiedScan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('photo', models.ImageField(storage=portal.storage.database_storage, upload_to='unidentified/%Y/%m/')),
                ('visitor_username', models.CharField(blank=True, db_index=True, max_length=150)),
                ('outcome', models.CharField(choices=[('NO_MATCH', 'No match'), ('SUGGESTION', 'Suggestion only')], db_index=True, default='NO_MATCH', max_length=20)),
                ('model_label', models.CharField(blank=True, max_length=60)),
                ('model_score', models.FloatField(blank=True, null=True)),
                ('suggested_name', models.CharField(blank=True, max_length=150)),
                ('scanned_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('status', models.CharField(choices=[('NEW', 'New'), ('LABELLED', 'Labelled'), ('DISMISSED', 'Dismissed')], db_index=True, default='NEW', max_length=10)),
                ('kind', models.CharField(blank=True, choices=[('PLANT', 'Plant'), ('LANDMARK', 'Landmark'), ('OTHER', 'Other / not useful')], max_length=10)),
                ('identified_as', models.CharField(blank=True, max_length=150)),
                ('notes', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-scanned_at'],
            },
        ),
        migrations.RunPython(add_feature, remove_feature),
    ]
