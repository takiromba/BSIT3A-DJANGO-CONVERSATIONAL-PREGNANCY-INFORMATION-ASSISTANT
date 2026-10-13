from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import PregnancyProfileForm, PrenatalAppointmentForm
from .models import PregnancyProfile, PregnancyTopic, PrenatalAppointment, TopicBookmark


@login_required(login_url="login")
def pregnancy_profile(request):
    profile, _created = PregnancyProfile.objects.get_or_create(user=request.user)
    form = PregnancyProfileForm(
        request.POST or None,
        instance=profile,
    )
    appointment_form = PrenatalAppointmentForm()
    if request.method == "POST" and "save_profile" in request.POST and form.is_valid():
        form.save()
        messages.success(request, "Your pregnancy profile has been updated.")
        return redirect("pregnancy_profile")
    if request.method == "POST" and "add_appointment" in request.POST:
        appointment_form = PrenatalAppointmentForm(request.POST)
        if appointment_form.is_valid():
            appointment = appointment_form.save(commit=False)
            appointment.profile = profile
            appointment.save()
            messages.success(request, "Your appointment was saved.")
            return redirect("pregnancy_profile")
    return render(
        request,
        "pregnancy/prenatal_profile.html",
        {
            "profile": profile,
            "form": form,
            "appointment_form": appointment_form,
            "appointments": profile.appointments.filter(
                scheduled_at__gte=timezone.now(),
            )[:20],
        },
    )


@login_required(login_url="login")
@require_POST
def delete_appointment(request, appointment_id):
    appointment = get_object_or_404(
        PrenatalAppointment.objects.filter(profile__user=request.user),
        pk=appointment_id,
    )
    appointment.delete()
    messages.success(request, "Appointment removed.")
    return redirect("pregnancy_profile")


@login_required(login_url="login")
@require_POST
def toggle_bookmark(request, topic_id):
    topic = get_object_or_404(
        PregnancyTopic.objects.filter(is_published=True),
        pk=topic_id,
    )
    bookmark, created = TopicBookmark.objects.get_or_create(
        user=request.user,
        topic=topic,
    )
    if not created:
        bookmark.delete()
        messages.success(request, "Topic removed from your saved topics.")
    else:
        messages.success(request, "Topic saved for later.")
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("topic_detail", slug=topic.slug)


@login_required(login_url="login")
def bookmarks(request):
    saved_topics = PregnancyTopic.objects.filter(
        bookmarks__user=request.user,
        is_published=True,
    )
    return render(
        request,
        "pregnancy/bookmarks.html",
        {
            "topics": saved_topics,
        },
    )
