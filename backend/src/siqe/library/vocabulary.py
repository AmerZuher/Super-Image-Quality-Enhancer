"""Words the Library can tag an image with automatically, and the phrases CLIP compares against.

A tag is chosen when its phrase is clearly closer to the image than the other phrases are
(zero-shot classification), so the list mixes subjects, scenes and kinds of photo. Keep tags
short, lowercase and plural-free; they show on cards and are searchable.
"""

TAGS: dict[str, str] = {
    # people and animals
    "people": "a photo of people",
    "portrait": "a portrait photo of a person",
    "selfie": "a selfie",
    "baby": "a photo of a baby",
    "dog": "a photo of a dog",
    "cat": "a photo of a cat",
    "bird": "a photo of a bird",
    "horse": "a photo of a horse",
    "elephant": "a photo of an elephant",
    "deer": "a photo of a deer or moose",
    "wildlife": "a wildlife photo of a wild animal",
    "fish": "a photo of fish",
    "insect": "a photo of an insect",
    # nature and landscape
    "landscape": "a landscape photo",
    "mountain": "a photo of mountains",
    "lake": "a photo of a lake",
    "sea": "a photo of the sea",
    "beach": "a photo of a beach",
    "river": "a photo of a river",
    "waterfall": "a photo of a waterfall",
    "forest": "a photo of a forest",
    "tree": "a photo of a tree",
    "valley": "a photo of a valley",
    "desert": "a photo of a desert",
    "snow": "a photo of snow",
    "sky": "a photo of the sky and clouds",
    "sunset": "a photo of a sunset or sunrise",
    "night": "a photo taken at night",
    "reflection": "a photo of a reflection in water",
    "flower": "a photo of a flower",
    "leaf": "a close-up photo of a leaf",
    "plant": "a photo of a plant",
    "garden": "a photo of a garden",
    # places and things
    "city": "a photo of a city",
    "street": "a photo of a street",
    "building": "a photo of a building",
    "architecture": "a photo of architecture",
    "interior": "a photo of a room interior",
    "road": "a photo of a road",
    "bridge": "a photo of a bridge",
    "pier": "a photo of a pier or jetty",
    "boat": "a photo of a boat",
    "car": "a photo of a car",
    "bicycle": "a photo of a bicycle",
    "train": "a photo of a train",
    "aircraft": "a photo of an aeroplane",
    "food": "a photo of food",
    "fruit": "a photo of fruit",
    "drink": "a photo of a drink",
    "feather": "a photo of a feather",
    "toy": "a photo of a toy",
    "book": "a photo of a book",
    "computer": "a photo of a computer",
    "phone": "a photo of a mobile phone",
    "clothing": "a photo of clothing",
    "jewellery": "a photo of jewellery",
    "sport": "a photo of sport",
    "music": "a photo of a musical instrument",
    "art": "a painting or artwork",
    # kinds of image
    "macro": "a macro photo, extreme close-up",
    "aerial": "an aerial photo taken from above",
    "black and white": "a black and white photo",
    "screenshot": "a screenshot of a computer screen",
    "document": "a photo of a document with text",
    "drawing": "a drawing or illustration",
    "logo": "a logo or icon",
    "pattern": "an abstract pattern or texture",
    "splash": "a photo of a water splash",
    "underwater": "an underwater photo",
}

# A tag is applied when its softmax share (at CLIP's own temperature) is at least MIN_SHARE and
# its similarity beats the image's average over all phrases by MIN_LIFT; at most MAX_TAGS per
# image, best first. The lift keeps featureless images (a flat colour, a blank scan) untagged:
# on the samples, real subjects lift 0.10 or more, flat colours 0.07 or less.
MIN_SHARE = 0.05
MIN_LIFT = 0.09
MAX_TAGS = 4
