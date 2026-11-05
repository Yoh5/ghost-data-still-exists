# -*- coding: utf-8 -*-
"""Genere assets/cover.png, l'image d'en-tete du README.

Typographie seule, pas de capture d'ecran : une capture vieillit a la premiere
ligne de code changee, et GitHub la sert aussi en apercu de lien, ou elle est
illisible. Palette alignee sur le CV (bleu 1D4ED8, orange F59E0B) pour que les
depots et le CV se reconnaissent.
"""
import os

from PIL import Image, ImageDraw, ImageFont

ICI = os.path.dirname(os.path.abspath(__file__))
L, H = 1280, 480
FOND = (15, 23, 42)
BLANC = (248, 250, 252)
ARDOISE = (148, 163, 184)
BLEU = (96, 165, 250)
ORANGE = (245, 158, 11)

POLICES = "C:/Windows/Fonts/"


def police(nom, taille):
    for essai in (nom, "segoeui.ttf", "arial.ttf"):
        chemin = os.path.join(POLICES, essai)
        if os.path.exists(chemin):
            return ImageFont.truetype(chemin, taille)
    return ImageFont.load_default()


img = Image.new("RGB", (L, H), FOND)
d = ImageDraw.Draw(img)

# Le pointille vertical du CV, repris en filigrane a droite.
x = L - 150
y = 40
while y < H - 40:
    d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(30, 41, 59))
    y += 18

MG = 80
d.text((MG, 92), "Ghost Data Still Exists", font=police("segoeuib.ttf", 62), fill=BLANC)
d.text((MG, 176), "A deletion-audit agent that reports the ceiling it cannot pass",
       font=police("segoeui.ttf", 28), fill=ARDOISE)

d.rectangle([MG, 240, MG + 90, 244], fill=ORANGE)

d.text((MG, 278),
       "It reaches 0.829 of the answer. The evidence only allows 0.912.",
       font=police("segoeuib.ttf", 27), fill=BLEU)
d.text((MG, 318),
       "Seventeen resources appear in no evidence file at all - so the README\n"
       "reports 91 % of what is reachable, not a score that flatters it.",
       font=police("segoeui.ttf", 23), fill=ARDOISE, spacing=9)

d.text((MG, 410), "Python  \u00b7  standard library only  \u00b7  157 tests  \u00b7  Apache-2.0",
       font=police("segoeui.ttf", 21), fill=(100, 116, 139))

sortie = os.path.join(ICI, "cover.png")
img.save(sortie, optimize=True)
print("ecrit :", sortie, os.path.getsize(sortie) // 1024, "Ko")
