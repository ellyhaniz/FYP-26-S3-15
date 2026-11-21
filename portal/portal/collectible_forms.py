from django import forms

from . import classifier
from .forms import LineBreakTextarea, RecordForm, tidy, tidy_block
from .models import (ArchitectureRecord, BotanicalRecord, Collectible, CollectibleCategory)


class CollectibleForm(RecordForm):
    """SA-04 / SA-06. Inherits the image checks (type, size) and the status field from RecordForm."""

    status = forms.ChoiceField(
        choices=Collectible.STATUSES, initial=Collectible.PUBLISHED,
        help_text="Draft collectibles are hidden from visitors.")

    linked_record = forms.ChoiceField(
        label="Linked record",
        error_messages={"required": "Choose the record this collectible is linked to.",
                        "invalid_choice": "That record no longer exists. Choose another one."},
        help_text="The plant or structure a visitor must identify to unlock this card. "
                  "Only Published (verified) records can be linked, and each record can have "
                  "only one collectible.")

    class Meta:
        model = Collectible
        fields = ["name", "category", "rarity", "description", "image", "status", "model_label"]
        labels = {"name": "Collectible name", "category": "Category", "rarity": "Rarity level",
                  "description": "Description", "image": "Card image",
                  "model_label": "Scan label"}
        widgets = {
            "description": LineBreakTextarea(attrs={"rows": 4}),
            "image": forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        }
        help_texts = {
            "image": "JPG, PNG or WebP, up to 5 MB. When editing, leave empty to keep the current image.",
            "model_label": "What the PlantDex model calls this plant or structure. Visitors unlock the "
                           "card by scanning it. If it isn't in the list, the model wasn't trained on "
                           "it: choose \"Not scannable yet\" and the card stays locked until the "
                           "model is retrained with photos of it.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = CollectibleCategory.objects.all()
        self.fields["category"].empty_label = "Choose a category"
        self.fields["linked_record"].choices = self._record_choices()
        if self.instance.pk:                      # editing: preselect the current link
            kind = "b" if self.instance.botanical_record_id else "a"
            self.initial["linked_record"] = f"{kind}:{self.instance.linked_record.pk}"
        self.fields["model_label"].widget = forms.Select(choices=self._label_choices())
        self.order_fields(["name", "linked_record", "category", "rarity",
                           "description", "image", "status", "model_label"])

    def _label_choices(self):
        """The model's labels, marked when another card already uses one. A label the
        current model no longer has is kept as an option so editing doesn't drop it."""
        used = dict(Collectible.objects.exclude(model_label="").exclude(pk=self.instance.pk)
                    .values_list("model_label", "name"))
        labels = classifier.model_labels()
        choices = [("", "Not scannable yet (model doesn't recognise it)")]
        for label in sorted(labels, key=classifier.display_name):
            text = f"{classifier.display_name(label)}  ({label})"
            choices.append((label, f"{text}  (used by '{used[label]}')" if label in used else text))
        current = self.instance.model_label
        if current and current not in labels:
            choices.append((current, f"{current}  (not in the current model)"))
        return choices

    # ---- the drop-down ----------------------------------------------------
    def _record_choices(self):
        """Every existing record, with a marker when it cannot be chosen (the use-case
        messages are produced on submit, so the person sees *why*)."""
        own_b, own_a = self.instance.botanical_record_id, self.instance.architecture_record_id
        taken_b = set(Collectible.objects.exclude(botanical_record=None)
                      .exclude(botanical_record_id=own_b).values_list("botanical_record_id", flat=True))
        taken_a = set(Collectible.objects.exclude(architecture_record=None)
                      .exclude(architecture_record_id=own_a).values_list("architecture_record_id", flat=True))

        def label(text, record, taken):
            if record.status != "PUBLISHED":
                return f"{text}  (Draft, not verified)"
            if record.pk in taken:
                return f"{text}  (already has a collectible)"
            return text

        botanical_records = list(BotanicalRecord.objects.order_by("common_name"))
        architecture_records = list(ArchitectureRecord.objects.order_by("name"))
        # Nothing can be linked: every record is a Draft or already has a collectible.
        self.no_free_records = not (
            any(r.status == "PUBLISHED" and r.pk not in taken_b for r in botanical_records)
            or any(r.status == "PUBLISHED" and r.pk not in taken_a for r in architecture_records))

        botanical = [(f"b:{r.pk}", label(f"{r.common_name} ({r.scientific_name})", r, taken_b))
                     for r in botanical_records]
        architecture = [(f"a:{r.pk}", label(r.name, r, taken_a))
                        for r in architecture_records]
        return [("", "Choose a record")] + (
            [("Botanical records", botanical)] if botanical else []) + (
            [("Architecture records", architecture)] if architecture else [])

    # ---- validation (the alternative flows of SA-04 / SA-06) ---------------
    def clean_linked_record(self):
        value = self.cleaned_data["linked_record"]
        kind, _, pk = value.partition(":")
        model = {"b": BotanicalRecord, "a": ArchitectureRecord}.get(kind)
        record = model.objects.filter(pk=pk).first() if model and pk.isdigit() else None
        if record is None:
            raise forms.ValidationError("That record no longer exists. Choose another one.")
        if record.status != "PUBLISHED":
            raise forms.ValidationError(
                "This record is not verified yet (it is a Draft). Ask a Researcher to publish it first.")
        existing = Collectible.objects.filter(**{("botanical_record" if kind == "b" else "architecture_record"): record})
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError(
                f"A collectible already exists for this record: '{existing.first().name}'.")
        return kind, record

    def clean_name(self):
        return tidy(self.cleaned_data["name"])

    def clean_model_label(self):
        label = tidy(self.cleaned_data.get("model_label") or "").lower()
        if label and label not in classifier.model_labels() and label != self.instance.model_label:
            raise forms.ValidationError(
                "The PlantDex model doesn't recognise this label. Choose one from the list, "
                "or \"Not scannable yet\".")
        if label:
            taken = Collectible.objects.filter(model_label=label).exclude(pk=self.instance.pk).first()
            if taken:
                raise forms.ValidationError(f"The collectible '{taken.name}' already uses this scan label.")
        return label

    def clean_description(self):
        return tidy_block(self.cleaned_data["description"])

    @property
    def link_changed(self):
        return "linked_record" in self.changed_data

    # ---- saving ----------------------------------------------------------
    def save(self, commit=True):
        obj = super().save(commit=False)
        kind, record = self.cleaned_data["linked_record"]
        obj.botanical_record = record if kind == "b" else None
        obj.architecture_record = record if kind == "a" else None
        if commit:
            obj.save()
        return obj
