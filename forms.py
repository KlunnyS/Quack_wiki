from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, FileField, SubmitField, PasswordField, IntegerField,HiddenField
from wtforms.validators import DataRequired, Length, EqualTo, Email
from flask_wtf.file import FileAllowed

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=30)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm password',
                                     validators=[DataRequired(), EqualTo('password', message='Passwords don\'t match')])
    submit = SubmitField('Register')

class RoleForm(FlaskForm):
    role = SelectField("Role", choices=[
        ("user", "User"),
        ("writer", "Writer"),
        ("admin", "Admin"),
        ], validators=[DataRequired()])
    submit = SubmitField("Change")

class ProfileForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=30)])
    public_display_name = StringField('Public display name', validators=[Length(max=80)])
    public_bio = TextAreaField('Public bio', validators=[Length(max=600)])
    profile_image = FileField('Profile picture', validators=[
        FileAllowed(["jpg", "jpeg", "png", "gif", "webp"], "Images only.")
    ])
    submit = SubmitField('Save profile')

class PasswordChangeForm(FlaskForm):
    current_password = PasswordField('Current password', validators=[DataRequired()])
    password = PasswordField('New password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        'Confirm new password',
        validators=[DataRequired(), EqualTo('password', message='Passwords don\'t match')]
    )
    submit = SubmitField('Change password')

class ArticleForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(min=3, max=120)])
    summary = TextAreaField("Summary", validators=[Length(max=1000)])
    content = TextAreaField("Content", validators=[DataRequired()])
    infobox_data = TextAreaField("Infobox Fields", validators=[Length(max=3000)])
    image_file = FileField("Picture", validators=[
        FileAllowed(["jpg", "jpeg", "png", "gif", "webp"], "Images only.")
    ])
    tags = StringField("Tags (comma separated)")
    submit = SubmitField("Create Article")

class SiteSettingsForm(FlaskForm):
    hero_image = FileField("Community banner image", validators=[
        FileAllowed(["jpg", "jpeg", "png", "gif", "webp"], "Images only.")
    ])
    submit = SubmitField("Save Settings")
