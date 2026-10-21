"""Book content: the five practices and the list of other ideas.

Source: "How to Unrot Your Brain" by Colby Kultgen (2025).
The "why" text is our own honest summary of the evidence we found
(see docs/research/report.md). It is softer than the book where the
evidence is weak.
"""

from dataclasses import dataclass

# Practice states for a day. No row means not done (and not a rest day).
DONE = "done"
REST = "rest"


@dataclass(frozen=True)
class Practice:
    id: str
    title: str
    how: str
    why: str


PRACTICES = (
    Practice(
        id="phone",
        title="Phone curfew, 9 pm to 8 am",
        how="Phone away at night. Grayscale on. Non-essential alerts off.",
        why=(
            "Small randomized studies found that grayscale mode cut phone time "
            "by about 20 minutes a day.\n\n"
            "Large reviews link phone use at bedtime with worse sleep in "
            "children and teens. For adults there is only one small trial.\n\n"
            "For alerts: one study found that getting them in batches, 3 times "
            "a day, helped more than turning them all off."
        ),
    ),
    Practice(
        id="boredom",
        title="20 minutes with no device",
        how="A walk, a meal, or a queue, without a screen.",
        why=(
            "In four small experiments, walking helped people come up with "
            "more ideas (Oppezzo and Schwartz, 2014).\n\n"
            "The idea that boredom itself makes you creative rests on two "
            "small studies from 2014. Later results are mixed."
        ),
    ),
    Practice(
        id="write",
        title="Write",
        how="Note one story-worthy moment from today.",
        why=(
            "The book mentions a \"Nature study\". It is really a 2025 opinion "
            "piece in Nature Reviews Bioengineering called \"Writing is "
            "thinking\", not a study.\n\n"
            "It points to a brain-scan study of 36 people who wrote by hand. "
            "That study measured brain activity, not learning. Treat writing "
            "as a good habit, not a proven brain fix."
        ),
    ),
    Practice(
        id="research",
        title="Explore a topic",
        how="Follow your curiosity: an article, a lecture, a rabbit hole.",
        why=(
            "This is the author's advice. We found no study that tests it "
            "directly, so try it and see if it helps you."
        ),
    ),
    Practice(
        id="read",
        title="Read for fun",
        how="Any book you enjoy. Comics count.",
        why=(
            "A study of over 10,000 children linked early reading for pleasure "
            "with better thinking scores and better mental health.\n\n"
            "It shows a link, not proof, and it was about children, not adults."
        ),
    ),
)

PRACTICE_IDS = tuple(p.id for p in PRACTICES)

IDEAS = (
    "Do a crossword puzzle",
    "Memorize a song or poem",
    "Plant something and take care of it",
    "Write and mail a handwritten letter",
    "Watch a movie and try to analyze it",
    "Make a collage out of old magazines",
    "Start a book club with your friends",
    "Learn how to play a new card game",
    "Buy a recipe book and cook your way through it",
    "Build something with your hands (LEGO counts)",
    "Watch a TED Talk and discuss it with someone",
    "Go to a museum and study one piece in detail",
    "Make a playlist for someone you care about",
)

WALK_MINUTES = 20
