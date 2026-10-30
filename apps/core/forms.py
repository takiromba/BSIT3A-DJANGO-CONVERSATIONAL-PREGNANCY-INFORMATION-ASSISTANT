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


class PregnancyProfileForm(forms.ModelForm):
    privacy_acknowledgement = forms.BooleanField(
        required=False,
        label=_(
            "I have read and understood the Privacy & Data Policy, and I agree "
            "to the collection and use of my information as explained above."
        ),
        error_messages={
            "required": _(
                "Please acknowledge the Privacy & Data Policy before saving "
                "your profile."
            ),
        },
    )
    OPTIONAL_PROFILE_FIELDS = (
        "phone_number",
        "healthcare_provider",
        "city",
        "province",
        "postal_code",
        "emergency_contact_name",
        "emergency_contact_relationship",
        "emergency_contact_number",
    )

    first_name = forms.CharField(max_length=150, required=True, label=_("First name"))
    last_name = forms.CharField(max_length=150, required=True, label=_("Last name"))
    email = forms.EmailField(
        required=True,
        label=_("Email"),
        error_messages={"invalid": "Please enter a valid email address."},
    )
    date_of_birth = forms.DateField(
        required=True,
        label=_("Date of birth"),
        widget=forms.DateInput(attrs={"type": "date"}),
        error_messages={
            "required": "Enter your date of birth to complete this form.",
        },
    )
    pregnancy_status = forms.ChoiceField(
        required=True,
        label=_("Pregnancy status"),
        choices=PregnancyProfile.PregnancyStatus.choices,
        error_messages={
            "required": "Select your pregnancy status to complete this form.",
        },
    )
    estimated_conception_date = forms.DateField(
        required=False,
        label=_("Estimated conception date"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    blood_type = forms.ChoiceField(
        required=False,
        label=_("Blood type (optional)"),
        choices=[
            ("", "Prefer not to say / Unknown"),
            *PregnancyProfile.BLOOD_TYPE_CHOICES,
        ],
    )

    class Meta:
        model = PregnancyProfile
        fields = (
            "date_of_birth",
            "pregnancy_status",
            "estimated_conception_date",
            "blood_type",
            "phone_number",
            "healthcare_provider",
            "city",
            "province",
            "postal_code",
            "emergency_contact_name",
            "emergency_contact_relationship",
            "emergency_contact_number",
        )
        labels = {
            "phone_number": _("Phone number"),
            "healthcare_provider": _("Healthcare provider"),
            "city": _("City"),
            "province": _("Province"),
            "postal_code": _("Postal code"),
            "emergency_contact_name": _("Emergency contact name"),
            "emergency_contact_relationship": _("Emergency contact relationship"),
            "emergency_contact_number": _("Emergency contact number"),
        }

    def __init__(
        self,
        *args,
        user=None,
        require_privacy_acknowledgement=False,
        **kwargs,
    ):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["privacy_acknowledgement"].required = (
            require_privacy_acknowledgement
        )
        if user is not None:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if self.user is None:
            return email
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("That email address is already in use.")
        return email

    def clean_date_of_birth(self):
        date_of_birth = self.cleaned_data.get("date_of_birth")
        if date_of_birth and date_of_birth > timezone.localdate():
            raise forms.ValidationError("The date of birth cannot be in the future.")
        return date_of_birth

    def clean_estimated_conception_date(self):
        conception_date = self.cleaned_data.get("estimated_conception_date")
        if conception_date and conception_date > timezone.localdate():
            raise forms.ValidationError(
                "The estimated conception date cannot be in the future."
            )
        return conception_date

    def clean(self):
        cleaned_data = super().clean()
        if self.is_bound:
            for field_name in self.OPTIONAL_PROFILE_FIELDS:
                if field_name not in self.data:
                    cleaned_data[field_name] = getattr(self.instance, field_name)
        status = cleaned_data.get("pregnancy_status")
        if (
            status == PregnancyProfile.PregnancyStatus.PREGNANT
            and not cleaned_data.get("estimated_conception_date")
            and "estimated_conception_date" not in self.errors
        ):
            self.add_error(
                "estimated_conception_date",
                "Enter an estimated conception date for a current pregnancy.",
            )
        return cleaned_data

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user is not None:
            profile.user = self.user
            self.user.first_name = self.cleaned_data["first_name"].strip()
            self.user.last_name = self.cleaned_data["last_name"].strip()
            self.user.email = self.cleaned_data["email"]
            if commit:
                self.user.save(update_fields=["first_name", "last_name", "email"])
        if commit:
            profile.save()
        return profile


class AccountDetailsForm(forms.Form):
    """Edit the authenticated user's own account details.

    The form never accepts a user identifier from the request; the view passes
    ``request.user`` explicitly so a submission can only ever update its owner.
    """

    first_name = forms.CharField(max_length=150, required=True, label=_("First name"))
    last_name = forms.CharField(max_length=150, required=True, label=_("Last name"))
    email = forms.EmailField(
        required=True,
        label=_("Email"),
        error_messages={"invalid": "Please enter a valid email address."},
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if self.user is None:
            return email
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("That email address is already in use.")
        return email

    def save(self):
        user = self.user
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.email = self.cleaned_data["email"]
        user.save(update_fields=["first_name", "last_name", "email"])
        return user


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
