"""WTForms definitions used by Quack Wiki routes."""

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileSize
from wtforms import FileField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length

MAX_IMAGE_UPLOAD_SIZE = 5 * 1024 * 1024
IMAGE_UPLOAD_SIZE_MESSAGE = "Image must be 5 MB or smaller."
IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp"]


# Public authentication forms used by register/login routes.
class LoginForm(FlaskForm):
    """Email/password login form."""

    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class RegisterForm(FlaskForm):
    """Public account registration form."""

    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=30)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm password',
                                     validators=[DataRequired(), EqualTo('password', message='Passwords don\'t match')])
    submit = SubmitField('Register')


# Admin dashboard form for role changes.
class RoleForm(FlaskForm):
    """Admin role assignment form."""

    role = SelectField("Role", choices=[
        ("user", "User"),
        ("writer", "Writer"),
        ("admin", "Admin"),
        ], validators=[DataRequired()])
    submit = SubmitField("Change")


# Account settings forms are split so profile edits and password changes validate independently.
class ProfileForm(FlaskForm):
    """User profile settings form."""

    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=30)])
    public_display_name = StringField('Public display name', validators=[Length(max=80)])
    public_bio = TextAreaField('Public bio', validators=[Length(max=600)])
    profile_image = FileField('Profile picture', validators=[
        FileAllowed(IMAGE_EXTENSIONS, "Images only."),
        FileSize(max_size=MAX_IMAGE_UPLOAD_SIZE, message=IMAGE_UPLOAD_SIZE_MESSAGE),
    ])
    submit = SubmitField('Save profile')


class PasswordChangeForm(FlaskForm):
    """Authenticated password change form."""

    current_password = PasswordField('Current password', validators=[DataRequired()])
    password = PasswordField('New password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        'Confirm new password',
        validators=[DataRequired(), EqualTo('password', message='Passwords don\'t match')]
    )
    submit = SubmitField('Change password')


# Article and site-settings forms both support image uploads with shared validation rules.
class ArticleForm(FlaskForm):
    """Create/edit form for article content and metadata."""

    title = StringField("Title", validators=[DataRequired(), Length(min=3, max=120)])
    summary = TextAreaField("Summary", validators=[Length(max=1000)])
    content = TextAreaField("Content", validators=[DataRequired()])
    infobox_data = TextAreaField("Infobox Fields", validators=[Length(max=3000)])
    image_file = FileField("Picture", validators=[
        FileAllowed(IMAGE_EXTENSIONS, "Images only."),
        FileSize(max_size=MAX_IMAGE_UPLOAD_SIZE, message=IMAGE_UPLOAD_SIZE_MESSAGE),
    ])
    tags = StringField("Tags (comma separated)")
    submit = SubmitField("Create Article")


class SiteSettingsForm(FlaskForm):
    """Admin form for updating site display settings."""

    hero_image = FileField("Community banner image", validators=[
        FileAllowed(IMAGE_EXTENSIONS, "Images only."),
        FileSize(max_size=MAX_IMAGE_UPLOAD_SIZE, message=IMAGE_UPLOAD_SIZE_MESSAGE),
    ])
    submit = SubmitField("Save Settings")
