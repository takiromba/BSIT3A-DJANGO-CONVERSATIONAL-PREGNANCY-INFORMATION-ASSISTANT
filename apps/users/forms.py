from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password


class UserForm(forms.ModelForm):
    username = forms.CharField(
        error_messages={"required": "Username is required."},
    )
    password = forms.CharField(
        widget=forms.PasswordInput,
        required=False,
        error_messages={"required": "Password is required for new users."},
    )
    email = forms.EmailField(required=False)

    class Meta:
        model = get_user_model()
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "password",
            "is_staff",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_password = self.instance.password if self.instance.pk else None

        self.fields["username"].required = True
        self.fields["username"].error_messages["required"] = "Username is required."
        self.fields["password"].error_messages[
            "required"
        ] = "Password is required for new users."
        for field in ("first_name", "last_name", "email"):
            self.fields[field].required = False
        if not self.instance.pk:
            self.fields["password"].required = True

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        conflicts = get_user_model().objects.filter(username__iexact=username)
        if self.instance.pk:
            conflicts = conflicts.exclude(pk=self.instance.pk)
        if conflicts.exists():
            raise forms.ValidationError("That username is already taken.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email:
            conflicts = get_user_model().objects.filter(email__iexact=email)
            if self.instance.pk:
                conflicts = conflicts.exclude(pk=self.instance.pk)
            if conflicts.exists():
                raise forms.ValidationError("That email is already in use.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            validate_password(password, self.instance)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)

        password = self.cleaned_data.get("password")

        # Only change password if user entered one
        if password:
            user.set_password(password)
        elif self._original_password is not None:
            user.password = self._original_password

        if commit:
            user.save()

        return user
