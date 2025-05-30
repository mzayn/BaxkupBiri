import boto.ec2
import pytz
from django.conf import settings
from django.utils.timezone import get_current_timezone
from rest_framework import serializers

from apps.console.account.models import CoreAccount
from apps.console.api.v1.utils.api_helpers import (
    CurrentMemberDefault,
    CurrentAccountDefault, IntegrationDefault, bs_decrypt, bs_encrypt,
)
from apps.console.connection.models import (
    CoreConnection,
    CoreIntegration,
    CoreConnectionLocation,
    CoreAuthUpCloud,
)
from apps.console.node.models import CoreNode
from apps.console.api.v1.account.serializers import CoreAccountSerializer
from apps.console.api.v1.connection.serializers import CoreIntegrationSerializer, CoreConnectionLocationSerializer



class CoreAuthUpCloudReadSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    password = serializers.SerializerMethodField()

    class Meta:
        model = CoreAuthUpCloud
        fields = (
            "id",
            "username",
            "password",
        )
        datatables_always_serialize = (
            "id",
            "username",
            "password",
        )

    def get_username(self, obj):
        return bs_decrypt(obj.username, self.context["encryption_key"])

    def get_password(self, obj):
        return bs_decrypt(obj.password, self.context["encryption_key"])


class CoreUpCloudConnectionReadSerializer(serializers.ModelSerializer):
    account = CoreAccountSerializer(read_only=True)
    integration = CoreIntegrationSerializer(read_only=True)
    location = CoreConnectionLocationSerializer(read_only=True)
    status_display = serializers.SerializerMethodField(read_only=True)
    created_display = serializers.SerializerMethodField()
    modified_display = serializers.SerializerMethodField()
    nodes_total = serializers.SerializerMethodField()
    cloud_total = serializers.SerializerMethodField()
    volume_total = serializers.SerializerMethodField()
    auth_upcloud = CoreAuthUpCloudReadSerializer(read_only=True)

    class Meta:
        model = CoreConnection
        fields = "__all__"
        datatables_always_serialize = (
            "id",
            "auth_upcloud",
        )

    @staticmethod
    def get_status_display(obj):
        return obj.get_status_display()

    @staticmethod
    def get_timezone(obj):
        return str(get_current_timezone())

    @staticmethod
    def get_created_display(obj):
        timezone = str(get_current_timezone())
        timezone = pytz.timezone(timezone)
        date_time = obj.created.astimezone(timezone).strftime("%b %d %Y - %I:%M%p")
        return date_time

    @staticmethod
    def get_modified_display(obj):
        timezone = str(get_current_timezone())
        timezone = pytz.timezone(timezone)
        date_time = obj.modified.astimezone(timezone).strftime("%b %d %Y - %I:%M%p")
        return date_time

    @staticmethod
    def get_nodes_total(obj):
        return obj.nodes.count()

    @staticmethod
    def get_cloud_total(obj):
        return obj.nodes.filter(type=CoreNode.Type.CLOUD).count()

    @staticmethod
    def get_volume_total(obj):
        return obj.nodes.filter(type=CoreNode.Type.VOLUME).count()


class CoreAuthUpCloudWriteSerializer(serializers.ModelSerializer):
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)
    connection = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = CoreAuthUpCloud
        fields = "__all__"

    def validate(self, data):
        try:
            import requests
            from requests.auth import HTTPBasicAuth

            username = data["username"]
            password = data["password"]
            client = HTTPBasicAuth(username, password)
            result = requests.get(
                settings.UPCLOUD_API + "/account", auth=client, verify=True, headers={"content-type": "application/json"}
            )
            if result.status_code != 200:
                raise serializers.ValidationError(
                    "Unable to authenticate. "
                    "Please check your username and password. "
                    "Make sure you whitelisted the BackupSheep Endpoint IP address."
                )
            data["username"] = bs_encrypt(username, self.context["encryption_key"])
            data["password"] = bs_encrypt(password, self.context["encryption_key"])
        except Exception as e:
            raise serializers.ValidationError(
                "Unable to authenticate. "
                "Please check your username and password. "
                "Make sure you enabled read and write permissions."
            )
        return data


class CoreUpCloudConnectionWriteSerializer(serializers.ModelSerializer):
    added_by = serializers.HiddenField(default=serializers.CreateOnlyDefault(CurrentMemberDefault()))
    account = serializers.HiddenField(default=serializers.CreateOnlyDefault(CurrentAccountDefault()))
    integration = serializers.HiddenField(
        default=serializers.CreateOnlyDefault(IntegrationDefault("upcloud"))
    )
    location = serializers.PrimaryKeyRelatedField(
        queryset=CoreConnectionLocation.objects.filter()
    )
    auth_upcloud = CoreAuthUpCloudWriteSerializer()

    class Meta:
        model = CoreConnection
        fields = "__all__"

    def create(self, validated_data):
        auth_upcloud = validated_data.pop("auth_upcloud", [])
        instance = CoreConnection.objects.create(**validated_data)
        auth_upcloud["connection"] = instance
        CoreAuthUpCloud.objects.create(**auth_upcloud)
        return instance

    def update(self, instance, validated_data):
        if validated_data.get("location"):
            if instance.location != validated_data["location"]:
                instance.update_scheduled_backup_locations(validated_data["location"])
        auth_upcloud = validated_data.pop("auth_upcloud", [])
        if len(auth_upcloud) > 0:
            super().update(instance.auth_upcloud, auth_upcloud)
        instance = super().update(instance, validated_data)
        return instance
