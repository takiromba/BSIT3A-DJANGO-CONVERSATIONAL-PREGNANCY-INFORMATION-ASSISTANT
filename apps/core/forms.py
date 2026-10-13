from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import PregnancyProfile, PrenatalAppointment

User = get_user_model()


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "autocomplete": "username",
                "autofocus": True,
            }
        )
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
            }
        )
    )


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=True, label=_("First name"))
    last_name = forms.CharField(max_length=150, required=True, label=_("Last name"))
    email = forms.EmailField(required=True, label=_("Email"))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Email already registered.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("password1")
            and cleaned_data.get("password2")
            and cleaned_data["password1"] != cleaned_data["password2"]
        ):
            self.add_error("password2", "Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    email = forms.EmailField(
        error_messages={"invalid": "Please enter a valid email address."},
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if (
            User.objects.filter(email__iexact=email)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError("That email address is already in use.")
        return email


class PregnancyProfileForm(forms.ModelForm):
    estimated_conception_date = forms.DateField(
        required=False,
        label=_("Estimated conception date"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    blood_type = forms.ChoiceField(
        required=False,
        label=_("Blood type (optional)"),
        choices=[("", "---------"), *PregnancyProfile.BLOOD_TYPE_CHOICES],
    )

    class Meta:
        model = PregnancyProfile
        fields = ("estimated_conception_date", "blood_type")

    def clean_estimated_conception_date(self):
        conception_date = self.cleaned_data.get("estimated_conception_date")
        if conception_date and conception_date > timezone.localdate():
            raise forms.ValidationError(
                "The estimated conception date cannot be in the future."
            )
        return conception_date


class PrenatalAppointmentForm(forms.ModelForm):
    title = forms.CharField(label=_("Appointment title"))
    scheduled_at = forms.DateTimeField(
        label=_("Date and time"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    notes = forms.CharField(required=False, label=_("Notes"), widget=forms.Textarea)
    reminder_enabled = forms.BooleanField(
        required=False,
        label=_("Show this reminder in the app"),
    )

    class Meta:
        model = PrenatalAppointment
        fields = ("title", "scheduled_at", "notes", "reminder_enabled")
