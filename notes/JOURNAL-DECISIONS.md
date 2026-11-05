# Journal de décisions — Orchestrate, 24-25 octobre 2026

> **À remplir pendant le sprint, pas après.** Un journal écrit dimanche matin
> est une reconstruction ; le juge le sent. Une entrée prend 90 secondes.

## La forme

Une entrée par choix **non évident**. Trois lignes obligatoires :

- **Choisi :** ce que j'ai fait
- **Écarté :** l'autre option, et pourquoi
- **Preuve :** le chiffre

Un choix sans alternative écartée n'est pas un choix, c'est un réflexe. Un choix
sans chiffre ne se défend pas — et si je n'ai pas mesuré, j'écris
**« pas mesuré »**. Le juge pardonne « je ne l'ai pas mesuré ». Il ne pardonne
pas une certitude inventée.

---

## Déjà décidé avant le départ

### D0 — Claude Code plutôt que Codex
- **Choisi :** Claude Code, l'outil que j'utilise tous les jours.
- **Écarté :** Codex, malgré 8 500 $ de crédits pour le podium.
- **Preuve :** les prix en espèces (1 200 $ / 300 $) n'exigent pas Codex ;
  apprendre une CLI d'agent pendant un sprint de 24 h coûte des heures que je
  n'ai pas, et des crédits dans un outil que je n'utilise pas valent moins que
  leur valeur affichée. Arbitrage fait **avant** le sprint, délibérément.

### D1 — Deux heures sans écrire de code
- **Choisi :** lire l'énoncé deux fois, écrire les critères de jugement, puis
  5 à 10 cas de test à la main, avant la première ligne de code.
- **Écarté :** commencer à coder à 14h31.
- **Preuve :** pas mesuré ici — mais c'est la méthode qui a produit tous mes
  résultats défendables (mesurer avant de conclure).

---

## Entrées du sprint

<!-- Copier ce bloc. Horodater. Ne rien effacer, même les choix abandonnés :
     un choix abandonné et son motif est une excellente réponse en entretien. -->

### D2 — Deux heures de mesure avant la première ligne de code · 14h30-15h30
- **Choisi :** lire l'énoncé, cloner le repo, puis écrire quatre scripts jetables qui
  mesurent la structure des 32 cas corrigés et des 518 cas à rendre, avant de concevoir.
- **Écarté :** coder depuis la lecture de l'énoncé, comme la majorité des 35 000 inscrits.
- **Preuve :** les mesures ont renversé deux de mes priorités en une heure. (1) Je croyais
  que détecter les demandes non-suppression était le risque n°1 : c'est **10 cas sur 518**
  (1,9 %), tous dans `case_533`-`case_542`. (2) Je croyais devoir faire produire le plan
  d'étapes par un modèle : l'ordre est **reconstructible mécaniquement, 32/32**. Sans la
  mesure, j'aurais mis mes heures aux deux mauvais endroits.

### D3 — Un seul moteur, pas deux · 15h00
- **Choisi :** un seul chemin de calcul. On dérive l'état final exigé de chaque ressource
  depuis `deletion_rules.csv`, on établit l'état observé à `audit_at`, et **l'écart entre
  les deux est la réponse**. `COMPLETE` est le cas où l'ensemble des écarts est vide.
- **Écarté :** deux branches séparées, une qui prouve la conformité et une qui planifie la
  remédiation — la lecture naïve de l'énoncé, qui décrit bien deux comportements.
- **Preuve :** mesuré sur les exemples — **21 des 22** cas INCOMPLETE contiennent des
  étapes de vérification sur des ressources qui n'ont eu **ni finding ni remédiation**,
  c'est-à-dire déjà conformes. Le bloc de vérification d'un cas INCOMPLETE a donc la même
  forme que celui d'un cas COMPLETE. Deux branches auraient dupliqué cette logique et
  dérivé l'une de l'autre. Et **22/22** des INCOMPLETE montrent une bijection exacte
  finding ↔ remédiation sur la même ressource, ce qui confirme que l'écart est l'unité.

### D4 — L'ordre des étapes est du code, pas du modèle · 15h20
- **Choisi :** trier par (phase, ordre du tableau de l'énoncé, `system_id`, `resource_id`)
  et numéroter. Une étape ne porte que `(operation, system_id, resource_id, evidence_id)` :
  `phase` et `state` sont des **fonctions** de `operation` dans le tableau de l'énoncé,
  donc dérivées à la sérialisation au lieu d'être transportées et risquées.
- **Écarté :** demander l'ordre au modèle, ou le vérifier après coup.
- **Preuve :** test `[order]` dans `code/evaluation/score_samples.py` — je prends les
  étapes officielles, je **mélange** leur ordre, je les re-trie avec ma règle, et j'exige
  l'identité au champ près : **32/32**. L'ordre ne peut plus régresser sans que le test
  tombe. Coût en appels de modèle : zéro.

### D5 — La notation écrite avant le premier prédicteur · 15h25
- **Choisi :** `code/audit/scoring.py` et son autotest existent **avant** qu'il y ait
  quoi que ce soit à noter. Un cas absent des prédictions compte comme un échec total,
  jamais ignoré.
- **Écarté :** noter à la main sur quelques cas, ou faire confiance à l'œil.
- **Preuve :** l'autotest attrape un instrument cassé. L'oracle (les réponses soumises
  comme prédictions) doit rendre 1,000 partout — il le fait. Et les étapes **mélangées**
  rendent F1 1,000 mais séquence 0,094 : les deux métriques mesurent bien des choses
  différentes, donc « bonnes étapes, mauvais ordre » ne peut pas se cacher derrière un
  bon F1. Un noteur qui ne peut pas échouer n'est pas un noteur.

### D6 — Ne jamais brancher sur `case_id` · 15h10
- **Choisi :** l'intention se lit dans le texte de la demande, par un modèle, sur le texte
  entier.
- **Écarté :** deux raccourcis qui marcheraient sur ce fichier précis. (1) Un filtre par
  mots-clés. (2) Coder la plage `case_533`-`case_542`, qui est contiguë et donnerait
  10/10.
- **Preuve :** le raccourci par mots-clés note ces cas **à l'envers** : 5 des 10 contiennent
  un verbe de suppression dans une négation (« I am not asking for deletion », « Do not
  close the account », « please don't delete or change anything »). Et le raccourci par
  identifiant est exactement le « case-family shortcut » interdit par `AGENTS.md` §6.7.
  Un test mélangera les `case_id` et exigera que les décisions ne bougent pas.

---

## Les mesures, au fil de l'eau

| heure | version | ce qui a changé | statut | séquence | notes |
|---|---|---|---|---|---|
| 15h25 | harnais | notation + sérialiseur, aucun prédicteur | — | — | ordre officiel reproduit **32/32** ; oracle 1,000 partout |
| 15h25 | référence | tout INCOMPLETE, aucune étape | **0,688** | 0,000 | la classe majoritaire |
| 15h25 | référence | tout COMPLETE, aucune étape | 0,312 | 0,000 | |
| 15h25 | référence | **faire confiance à `reported_status`** | **0,531** | 0,000 | **pire que la classe majoritaire** |

### D7 — Un seul « Observation » pour 46 familles de fichiers · 14h55
- **Choisi :** une seule forme de sortie — *(système, ressource, catégorie, état, sujet)* —
  et un **unique** extracteur clé-valeur pour les dix formats de logs. Les instantanés SQL
  sont **exécutés avec sqlite3**, pas lus à la regex. Et l'extraction **ne décide rien** :
  savoir si un email stocké est une violation appartient à l'étape de politique.
- **Écarté :** un parseur par famille (46), et une regex sur les `INSERT`.
- **Preuve :** les 46 familles n'énoncent qu'un sous-ensemble des mêmes cinq choses — mesuré
  en lisant une de chaque. Et la regex sur les `INSERT` casse dès qu'une valeur contient une
  virgule ou une apostrophe : ces fichiers portent des noms de personnes et des extraits de
  messages. Résultat : 3 173 observations depuis 62 fichiers, 15 restants = images et PDF.

### D8 — `present` est à trois états, pas booléen · 15h00
- **Choisi :** `present` vaut `True`, `False` ou **`None`**. `None` = « la preuve mentionne
  la ressource sans établir son état » (une recherche commencée et jamais terminée).
- **Écarté :** un booléen, avec `False` par défaut.
- **Preuve :** pas un chiffre mais un raisonnement que j'assume — confondre « absent » et
  « personne n'a regardé » est **exactement** la façon dont un audit conclut qu'un
  enregistrement a disparu alors que la vérité est que nul ne l'a vérifié. C'est le
  *fail-closed* au niveau du type : l'incertitude ne peut pas se dégrader en certitude par
  distraction. Même règle qu'au tit-for-tat : un coup non lu ne se devine pas.

### D9 — La fenêtre de rafale choisie par balayage, pas par un chiffre rond · 15h03
- **Choisi :** **3 heures**. Les lignes d'activité d'une demande forment une rafale ; le lien
  se propage depuis une amorce **ancrée dans une preuve**, jamais depuis la rafale seule.
- **Écarté :** 6 h, 24 h (le réflexe « une journée »), et l'attribution par co-occurrence
  pure.
- **Preuve :** balayage complet (`code/evaluation/sweep_window.py`). Le rappel **plafonne à
  0,775 dès 3 h** — 0,631 à 30 min, 0,667 à 1 h, 0,757 à 2 h, puis plat jusqu'à 48 h —
  tandis que la précision ne fait que **tomber** : 0,287 à 3 h, 0,258 à 6 h, 0,181 à 24 h,
  0,085 à 48 h. Tout ce qui est plus large n'achète rien et coûte du bruit. Les chiffres sont
  écrits à côté de la constante pour que le choix soit re-dérivable.

### D10 — Une hypothèse testée puis jetée : la convention de numérotation · 15h02
- **Choisi :** rien. Aucun code ne dépend de cette idée.
- **Écarté :** « le numéro de la ressource suit le numéro de l'utilisateur »
  (`user_01` → `account_001`), qui se vérifie sur les premiers cas et qui aurait été
  tentante.
- **Preuve :** testée sur les **111** ressources citées par les réponses officielles — elle
  tient **8 fois**. C'est une coïncidence des cas à petit numéro, pas une règle. Je la
  consigne parce qu'un piège évité vaut une réponse d'entretien.

| 15h04 | identité | résolution email actuel **ou** historique | — | — | **518/518** cas résolus ; **100 cas** arrivent avec un email **historique** (19 %) |
| 14h58 | preuves | lecteurs structurés + tokeniseur unique | — | — | 3 173 observations, 62/94 fichiers lus, rappel ressources **0,414** |
| 15h00 | correctif | aiguillage du fichier de passation (nom daté) | — | — | rappel **0,414 → 0,532** ; cas 11 ancré sur `evidence_03` |
| 15h04 | inventaire | amorce ancrée + rafale d'activité, fenêtre 3 h | — | — | rappel **0,532 → 0,775** ; plafond mesuré à 0,90 sans les images |

### D11 — La rafale d'activité, construite puis désactivée · 15h12
- **Choisi :** ne garder que les ressources **ancrées dans une preuve**. La rafale reste dans
  le code derrière `--burst`.
- **Écarté :** l'attribution par co-occurrence temporelle, que j'avais pourtant mesurée et
  retenue une heure plus tôt (D9).
- **Preuve :** le diff cas par cas a montré qu'elle ramassait les ressources **d'autres
  personnes** — le cas 11 produisait des findings contre `search_5960` et `analytics_5715`,
  et **123 vérifications parasites** sur 32 cas. Avec : F1 étapes 0,580, précision 0,532.
  Sans : F1 **0,627**, précision **0,978**. *Inventer une exposition pour quelqu'un qui n'a
  rien demandé est une faute plus grave que d'en manquer une.* Je garde le drapeau parce que
  la comparaison **est** la justification du choix.

### D12 — La corrélation par `trace_id` · 15h16
- **Choisi :** regrouper les lignes de log par identifiant de trace avant d'en tirer quoi que
  ce soit.
- **Écarté :** lire chaque ligne isolément (ce que je faisais).
- **Preuve :** diagnostic par cause des ressources manquées — **27** d'entre elles étaient
  observées mais sans aucun identifiant de sujet. Une seule raison : dans tous les formats,
  l'email est sur la ligne `..._started` et l'identifiant de ressource sur la ligne
  `..._completed`. Lire ligne à ligne perd le lien **en silence** : la ressource est bien
  enregistrée, elle n'appartient simplement à personne. Statut **0,688 → 0,781**, F1 étapes
  0,627 → 0,671, et les `COMPLETE` passent à **10/10 sans faux positif**.

### D13 — La coupure `audit_at` reste entière · 15h18
- **Choisi :** ne relier une ressource au sujet que par des preuves capturées **avant**
  `audit_at`, comme pour l'établissement de l'état.
- **Écarté :** dissocier les deux — relier à n'importe quelle date, n'affirmer l'état que sur
  des preuves datées. L'idée est séduisante : savoir *à qui* appartient un enregistrement est
  un fait sur le monde, et un cas INCOMPLETE ne cite aucune preuve sur ses vérifications.
- **Preuve :** essayé, mesuré, **annulé**. Le rappel monte (0,513 → 0,523) et c'est la seule
  route vers 7 ressources citées, mais le statut tombe de **0,781 à 0,750** — deux verdicts
  `COMPLETE` corrects bloqués par des ressources dont l'état à la coupure est indéterminable —
  pour un F1 étapes **inchangé** (0,671). Resserrer le blocage n'a rien récupéré. Les chiffres
  sont écrits à côté du code annulé pour que la tentative ne soit pas refaite.

### D14 — Deux natures d'incertitude, pas une · 15h19
- **Choisi :** une ressource à **conserver** dont l'état n'est pas confirmé est notée mais ne
  renverse pas le verdict ; une ressource à supprimer / masquer / anonymiser / désactiver /
  bloquer dont l'état n'est pas confirmé **le renverse**.
- **Écarté :** traiter toute incertitude de la même façon (ce que je faisais).
- **Preuve :** ce ne sont pas les mêmes échecs. Ne pas prouver une **rétention** est un trou
  dans ma preuve ; ne pas prouver une **suppression** veut dire qu'une copie interdite peut
  survivre. Le *fail-closed* doit mordre là où le risque est, pas partout pareil.

| 15h20 | **v1 complète** | moteur politique + écart, sortie CSV | **0,781** | 0,094 | F1 étapes **0,658**, précision **0,970**, rappel 0,497 ; 518 lignes, 1 655 étapes, **0,2 s, zéro appel de modèle** |

> **La direction de l'erreur compte plus que son taux.** Les 7 erreurs de statut qui restent
> vont toutes dans le même sens : on dit **COMPLETE** alors que c'est **INCOMPLETE**. C'est
> exactement le fantôme de l'énoncé. Zéro erreur dans l'autre sens (10/10 des COMPLETE sont
> justes). Un agent d'audit qui se trompe dans ce sens-là est pire qu'inutile : il rassure.
> C'est la cible suivante, et c'est une réponse d'entretien en soi.

### D15 — L'absence de preuve n'est pas une preuve de conformité · 15h32
- **Choisi :** seules les preuves qui **énumèrent les champs** d'un enregistrement peuvent
  attester qu'un identifiant a disparu (`Observation.field_level`). Et `account_status`
  décrit le **compte**, pas l'existence de la ligne.
- **Écarté :** déduire « masqué » de l'absence d'email dans une ligne de log ; lire
  `account_status=DELETED` comme « enregistrement absent ».
- **Preuve :** c'était la **même erreur à trois endroits**, et elle valait 7 faux `COMPLETE`.
  Un log ne mentionne que les champs que le service a choisi de journaliser : n'y pas voir
  d'email ne dit rien sur ce que l'enregistrement stocke. Et une pierre tombale qui dit
  `DELETED` est une ligne **qui existe** — c'est tout son objet — ce qui masquait que
  `tombstone_9178` portait encore nom, email, téléphone et empreinte. Statut
  **0,781 → 0,938**, faux `COMPLETE` de 7 à 2.

### D16 — Vérifier avant de payer : les PDF ne sont pas un problème de vision · 15h38
- **Choisi :** extraire le texte des 4 PDF avec `pdfplumber`. **Zéro appel de modèle.**
- **Écarté :** les envoyer à un modèle multimodal avec les 11 images.
- **Preuve :** ce sont des documents générés par ReportLab avec de vraies polices, pas des
  scans — vérifié en lisant les en-têtes (`/Font` × 15). Et l'un d'eux,
  `delivery_correction_attachment.pdf`, **est** `evidence_58`, la preuve que la réponse
  officielle du cas 07 cite : il contient `support_001`, l'email et le téléphone du sujet, et
  le mot « attachment » — exactement ce qui distingue la règle 06 (supprimer) de la règle 05
  (masquer). Statut **0,938 → 0,969**, soit **31 cas sur 32**.

### D17 — Le filtre par mots-clés, mesuré au lieu d'être supposé · 15h42
- **Choisi :** un modèle lit le texte entier ; `KeywordBaseline` reste dans le code **pour
  être mesuré**.
- **Écarté :** le filtre par mots-clés seul.
- **Preuve :** rappel **0,400** — il rate **6 des 10**, et chacun des six contient un verbe de
  suppression **dans une négation**. Le modèle : précision **1,000**, rappel **1,000**. Et une
  corroboration indépendante : `system_activity.csv` compte exactement **10** lignes
  `CLASSIFY_REQUEST`, le classifieur en trouve **10**. Ces lignes servent à **vérifier**, pas
  à décider : ce sont des affirmations de workflow, et tout le problème porte là-dessus.

### D18 — Confirmer les refus un par un, parce que les deux sens ne coûtent pas pareil · 15h44
- **Choisi :** la passe en lot signale les candidats, puis **chaque refus est redemandé
  seul**.
- **Écarté :** accepter le verdict du lot.
- **Preuve :** se tromper dans un sens coûte **un plan en trop** ; se tromper dans l'autre
  rend `NOT_APPLICABLE` avec un plan **vide** et supprime tout l'audit — le même silence que
  celui où le fantôme s'était caché. Mesuré : le lot seul trouvait les 10 mais signalait
  aussi deux copies d'une demande de suppression parfaitement claire ; la seconde passe les a
  renversées, précision **0,833 → 1,000**, pour une douzaine d'appels.

### D19 — Le lot, et un bug d'invite trouvé en lisant la sortie · 15h45
- **Choisi :** classer 25 messages par appel. Et ajouter à l'invite que **relancer sur une
  suppression déjà demandée reste le même dossier**.
- **Écarté :** un appel par message (375 allers-retours, **369 s**) ; et accuser le modèle.
- **Preuve :** le lot ramène les 518 cas à **~15 appels**. Quant aux 8 exemples mal classés,
  la faute était à l'invite, pas au modèle : plusieurs textes sont des **relances**
  (« j'ai vu un vieux rapport disant que mon compte existait encore, vérifiez »). Ce n'est pas
  une demande non-suppression. Corrigé : **32/32** des exemples classés en suppression.

| 15h32 | états | `field_level` + `account_status` | **0,938** | 0,125 | faux `COMPLETE` 7 → 2 |
| 15h38 | PDF | lecteur de documents, zéro modèle | **0,969** | 0,125 | F1 étapes **0,697** ; 31/32 |
| 15h46 | **intention** | lot + confirmation des refus | — | — | P **1,000** R **1,000** ; **25 appels, 0,0106 $** pour 518 cas |
| 15h46 | **v2 complète** | sortie finale | **0,969** | 0,125 | 518 lignes, 1 720 étapes, 210 / 298 / 10 ; run à chaud **0,5 s** |

> **Le coût, puisqu'il est noté.** Les seuls appels de modèle de toute la chaîne sont la
> classification d'intention : **0,021 appel par cas**, **0,0106 $** pour les 518. Identité,
> lecture des preuves, politique, calcul de l'écart, ordre et sérialisation sont entièrement
> déterministes. Ce n'est pas de l'économie pour l'économie : ce qui est déterministe est
> **re-vérifiable**, et c'est ce qui rend les chiffres de ce journal défendables.

### D20 — La passe visuelle : construite, mesurée, **sans gain**, et gardée quand même · 15h52
- **Choisi :** la garder active, avec la réserve écrite noir sur blanc dans le rapport.
- **Écarté :** la supprimer (elle ne rapporte rien de mesurable) ; et la vanter (elle ne
  rapporte rien de mesurable).
- **Preuve :** 11 appels, 19 enregistrements extraits, et l'intersection avec les ressources
  citées par les réponses officielles est **vide**. Mais les captures concernent
  `ingrid.dahl@outlook.com` et `haruka.s1838@zoho.com` — soit `case_33` et `case_34`, dans
  les **518 à prédire**, pas dans les 32 étiquetés. Donc je ne peux **ni** démontrer son
  utilité **ni** conclure qu'elle est inutile. C'est exactement le genre de réponse que je
  veux pouvoir donner au juge : *« je l'ai mesurée, elle ne gagne rien sur les données
  étiquetées, et voici pourquoi je la garde malgré tout. »*

### D21 — Un `=null` explicite n'est pas du silence · 15h55
- **Choisi :** une ligne de log compte comme **énumération de champs** dès qu'elle rapporte
  un champ identifiant explicitement, **y compris à `null`**.
- **Écarté :** traiter tous les logs pareil (ma règle D15, trop large).
- **Preuve :** `requester_name=null requester_email=mori.ren@gmail.com requester_phone=null`
  n'est pas une mention, c'est un **relevé**. Et `lookup_key` reste de l'autre côté de la
  ligne : ce que quelqu'un a **cherché** n'est pas ce que l'enregistrement **contient**.
  F1 étapes **0,697 → 0,758**, rappel 0,554 → **0,632**, champs 0,369 → 0,459, citation des
  preuves 0,587 → 0,653. C'est D15 affinée par la mesure, pas renversée.

### D22 — Une limite mesurée, annoncée au lieu d'être cachée · 15h58
- **Choisi :** déclarer dans le rapport que **17 des 111 ressources citées ne figurent dans
  aucune preuve** — ni CSV, ni log, ni SQL, ni PDF, ni capture. Plafond de rappel ≈ **0,85**.
- **Écarté :** deviner le compte supprimé parmi les candidats de la fenêtre de suppression.
- **Preuve :** le bon compte est bien dans la fenêtre pour **21 cas sur 22** — mais
  accompagné de **8 à 43** autres, et rien ne les distingue. En prendre un, c'est deviner ;
  les prendre tous, c'est inventer une trentaine d'expositions par cas. *Un chiffre qu'on ne
  peut pas établir ne s'invente pas* — et un plafond annoncé vaut mieux qu'un score inexpliqué.

### D23 — Les rapports sont **générés**, pas rédigés · 16h00
- **Choisi :** `make_reports.py` produit `evaluation_report.md` et `usage_report.md` depuis un
  vrai run, avec `--cold` qui vide le cache pour que le coût annoncé soit celui d'un run
  propre.
- **Écarté :** les écrire à la main dimanche matin.
- **Preuve :** un rapport tapé à la fin décrit le run dont son auteur **se souvient**.
  Celui-ci décrit le run qui **vient d'avoir lieu**, et il est régénéré après chaque
  changement — il ne peut pas dériver du code qu'il décrit. Run à froid mesuré : **37 appels,
  448 836 tokens, 0,0743 $, 174 s, 0 échec**.

### D24 — Deux de mes quatre tests étaient faux · 15h57
- **Choisi :** corriger les **assertions**, pas le code.
- **Preuve :** le test « décoy » exigeait que `jonas.berglund@outlook.com` se résolve en un
  sujet — or ce n'est **pas une personne enregistrée**, il n'existe que dans la preuve, et
  c'est précisément ce qui le rend dangereux. Le test de coupure exigeait qu'une coupure plus
  ancienne cite **moins** de preuves — or c'est un **autre** instantané qui devient alors le
  plus récent disponible, ce qui est correct. Écrire un test qui échoue m'a forcé à énoncer la
  propriété juste au lieu de celle qui m'arrangeait. **4/4** après correction.

| 15h55 | relevés | `enumerated` + champs stockés | 0,969 | 0,156 | F1 étapes **0,758**, rappel **0,632**, preuves 0,653 |
| 16h00 | **livrables** | 4 cas propres, 2 rapports générés, README, requirements | — | — | run à froid **0,0743 $ / 37 appels** ; 518 lignes, 1 960 étapes |

### D25 — Changer d'objectif avant de changer d'algorithme · 16h08
- **Choisi :** balayer les stratégies d'attribution sur le **score de bout en bout**
  (statut + F1 étapes), pas sur « combien de ressources citées j'arrive à lister ».
- **Écarté :** mon propre balayage de 15h04, qui optimisait un **proxy**.
- **Preuve :** lister une ressource ne vaut rien si le plan qu'elle produit est faux, et
  c'est le plan qui est noté. Le proxy m'avait fait choisir une fenêtre de 3 h qui, mesurée
  sur le vrai score, **perdait** 3 verdicts. *C'est le changement d'objectif qui a rendu le
  reste soluble* — pas une meilleure idée d'algorithme.

### D26 — La rafale, reprise sur le bon axe · 16h10
- **Choisi :** définir la rafale par **contiguïté d'`activity_id`** et non par une fenêtre
  de temps — puis **les deux ensemble**.
- **Écarté :** la contiguïté seule ; le temps seul ; et l'abandon pur et simple (D11).
- **Preuve :** `activity_3851` supprime `account_7566`, `activity_3852` anonymise
  `analytics_9406` 24 minutes plus tard. Or `analytics_9406` porte `lookup_key=null`,
  `email=null`, `customer_reference=null` : **entièrement anonymisé**, donc par construction
  rattachable à personne. Cette adjacence est le **seul** lien existant dans le jeu de
  données. Mais la contiguïté seule donnait `search_1993` — qui appartient au cas 29 — aux
  cas 27 et 28, parce que rien dans le flux d'identifiants ne sépare deux rafales
  consécutives. Le temps les sépare ; seul, il ratisse toutes les rafales qui se recouvrent.
  **À 1 heure, le compromis disparaît.** D11 n'était pas fausse : elle était mesurée sur le
  mauvais axe.

### D27 — Une ressource par système, mesuré puis imposé · 16h12
- **Choisi :** au plus **une** ressource candidate par système, la mieux étayée.
- **Preuve :** sur les 111 ressources citées par les réponses officielles, le nombre par
  (cas, système) vaut 1 — **111 fois sur 111**. Une personne a un profil, une entrée
  d'index, un enregistrement analytique. Et « plusieurs candidats dans un même système » est
  **exactement la forme du bruit** de la rafale. Précision 0,719 → **0,879**.

### D28 — Un `status_code` 404 n'est pas un enregistrement · 16h11
- **Choisi :** une section nommée `profile_lookups` rapporte des **recherches**. Un code
  4xx et une charge utile explicitement `null` signifient **absent**.
- **Écarté :** `present=True` par défaut pour tout enregistrement d'un export de service.
- **Preuve :** `{"profile": null, "resource_id": "account_3866", "status_code": 404}` était
  compté comme un profil **existant** — c'est le service qui dit qu'il n'y en a pas. Trois
  verdicts `COMPLETE` corrects basculaient à cause de ça. Au passage, j'utilise maintenant
  l'`observed_at` de chaque enregistrement plutôt que la date du fichier, ce qui affine
  aussi la coupure `audit_at`.

| | configuration | statut | P | R | **F1** | séq | champs | preuves |
|---|---|---|---|---|---|---|---|---|
| | preuves seules | 0,969 | 0,946 | 0,632 | 0,758 | 0,156 | 0,459 | 0,653 |
| | + rafale, temps seul | 0,875 | 0,696 | 0,746 | 0,720 | 0,094 | 0,519 | — |
| | **+ rafale, ids contigus + 1 h + 1/système** | **0,969** | 0,939 | **0,715** | **0,812** | **0,188** | **0,606** | **0,787** |

> **Le compromis n'était pas une fatalité, c'était un bug.** Pendant une heure j'ai cru
> devoir choisir entre le statut et les étapes. En réalité deux défauts se cachaient dans
> l'arbitrage — les sections de recherche lues comme des enregistrements, et l'absence de
> contrainte « une ressource par système ». Une fois corrigés, la meilleure configuration
> **égale** le statut et **bat** tout le reste. *Quand un compromis paraît inévitable,
> chercher le bug avant d'arbitrer.*

### D29 — Sécuriser la livraison plutôt que gratter 0,02 de F1 · 16h25
- **Choisi :** tester la livraison de bout en bout — environnement virtuel neuf, install
  depuis `requirements.txt` seul, puis **extraction du ZIP dans un dossier vide** avec le
  seul `dataset/` à côté.
- **Écarté :** continuer à optimiser le rappel sur les 6 cas « bonne ressource, mauvaise
  opération ».
- **Preuve :** un score qu'on ne peut pas livrer ne vaut rien, et la livraison n'avait
  **jamais** été testée. Les deux modes passent, y compris **sans aucune clé d'API** : la
  sortie reste valide, les 10 cas non-suppression manquent, et le programme **le dit** au
  lieu de laisser un défaut ressembler à un jugement.

### D30 — Trois runs indépendants, sortie identique au bit près · 16h28
- **Preuve :** arbre de travail, copie en venv neuf, archive extraite — **même sha256**.
  Vérifié plutôt que supposé, et c'était utile : la passe visuelle a rendu **19** puis
  **20** enregistrements à température 0. Ça n'a changé aucune réponse (cohérent avec D20),
  mais c'est la raison pour laquelle la sortie des modèles est mise en cache sur le hachage
  de chaque fichier. Le rapport énonce **ce qui a été comparé**, pas un « c'est
  déterministe » en l'air.

### D31 — Le `.cache` dans l'archive, et la leçon · 16h30
- **Choisi :** l'empaquetage devient un **script qui vérifie l'archive finie** — pas de
  `.cache`, `.venv`, `__pycache__`, `dataset`, `.git`, `output.csv` ni `.env`, les cinq
  fichiers obligatoires présents, et un balayage des chaînes en forme de clé. Tout
  interdit **arrête** la fabrication ; rien n'est retiré en silence.
- **Preuve :** la première `code.zip` **contenait** `.cache/` — 36 fichiers de réponses de
  modèle dérivées du jeu de données, dans une archive où l'énoncé interdit explicitement
  les caches. Créé sans que je le remarque en lançant le paquet depuis son propre dossier.
  *Je l'ai vu parce que j'ai listé le contenu avant de faire confiance.* Une vérification
  qui est du code ne s'oublie pas à 12h55.

### D32 — Un détecteur qui crie tout le temps finit éteint · 16h32
- **Choisi :** ancrer les motifs sur la **forme** d'une clé (`sk-` + 20 caractères, en-tête
  PEM avec ses tirets), pas sur un préfixe nu.
- **Preuve :** mon propre garde-fou s'est attrapé **deux fois**. Il a signalé une session
  d'un **autre projet** que le constructeur de trace avait ramassée en prenant « les trois
  plus récentes » — corrigé en ne retenant que les sessions du jour, et c'est précisément
  l'intérêt de vérifier **l'artefact** plutôt que l'intention. Puis il a signalé
  `BEGIN PRIVATE KEY`… dans le transcript, parce que cette chaîne est dans **le code du
  détecteur**. Et `sk-` tout nu matche « task- » et « risk- ».

| 16h34 | **livraison** | 4 livrables fabriqués et vérifiés | 0,969 | 0,188 | `code.zip` 79 Ko · `output.csv` 444 Ko · `log.txt` 41 Ko · `agent-trace.zip` 2,1 Mo |

> **Ce qu'il reste de risque n'est plus technique.** Les quatre fichiers existent, sont
> vérifiés par un script, et l'archive a été lancée depuis une extraction vierge. Le risque
> restant est le mien : soumettre à l'heure, et savoir défendre tout ceci devant la caméra
> **dimanche** — pas lundi.

### D33 — Une **opération** n'est pas un **résultat** · 16h47
- **Choisi :** lire le `event_type` d'une ligne d'activité (`DELETE_RECORD`,
  `REDACT_RECORD`, `ANONYMIZE_RECORD`…) comme **la décision de politique** sur cet
  enregistrement. Restreint à `deletion_worker` et `privacy_intake` — un job d'indexation
  ne parle pas au nom de la politique.
- **Écarté :** déduire la règle de la seule catégorie de donnée (ce que je faisais) ; et,
  bien sûr, croire `reported_result`.
- **Preuve :** c'est la **seule** chose dans le jeu de données qui sépare deux
  enregistrements que les règles ne peuvent pas distinguer. `support_002` et `support_864`
  ont des identifiants interchangeables ; `activity_3596` tente `DELETE_RECORD` sur le
  premier (règle 06), `activity_3815` tente `REDACT_RECORD` sur le second (règle 05) —
  exactement le traitement des réponses officielles. **F1 étapes 0,812 → 0,846**, précision
  0,921 → 0,961, séquence 0,250 → 0,281.

  **La distinction que je défendrai :** `reported_status` et `reported_result` sont des
  affirmations sur *ce qui s'est passé* — je n'en lis **aucune**, et y croire note 0,531.
  Le **type d'opération** n'est pas une affirmation sur un état : c'est la lecture que
  l'organisation fait de **sa propre politique** pour cet enregistrement, écrite **avant**
  la tentative et suivie très souvent de `FAILED`. Lire la politique n'est pas croire le
  résultat.

### D34 — La preuve d'absence suit le lien, pas sa provenance · 16h44
- **Choisi :** une ressource atteinte par **la rafale de suppression du sujet lui-même**
  peut être prouvée absente ; une ressource sans aucun lien, non.
- **Écarté :** ma propre restriction de 16h05, qui n'acceptait que les ressources ancrées
  dans une preuve.
- **Preuve :** elle était juste quand « rafale » voulait dire « tout ce qui s'est passé
  dans les 3 heures ». Elle est devenue trop stricte quand « rafale » a voulu dire **le même
  bloc contigu de travail** : une ressource que la run de suppression du sujet a touchée
  *est* rattachée à lui par cette run. Séquence 0,188 → **0,250**, champs 0,606 → **0,658**.
  *Une garde se re-justifie quand ce qu'elle garde a changé de sens.*

| 16h50 | **politique par l'activité** | + 11 collections mappées | **0,969** | **0,281** | P **0,961** · R **0,756** · **F1 0,846** · champs **0,672** |

> **Rappel 0,756 sur un plafond mesuré de ~0,85 : 89 % de ce que ce jeu de données permet.**
> Le reste, ce sont les 15 ressources qui ne figurent dans aucune preuve.

### D35 — Chercher le vrai périmètre de l'entretien au lieu de le supposer · 17h05
- **Choisi :** aller lire la page d'aide et le blog officiels de HackerRank.
- **Preuve :** le mail nommait **quatre** sujets. La page officielle en liste **sept**, et
  **deux nous manquaient entièrement** : *implementation and code familiarity* et
  **production monitoring**. L'entretien vaut **30 %** de la note et est explicitement
  jugé sur *« honesty about limitations »*. Le blog ajoute que le juge sonde les
  **instructions embarquées dans les entrées** — de l'injection de prompt. *Une heure de
  recherche a révélé deux axes entiers sur lesquels on serait arrivés muets.*

### D36 — Écrire les tests a trouvé trois bugs en une heure · 17h20
- **Choisi :** une vraie suite — **91 tests**, bibliothèque standard uniquement, et le
  contrat de sortie vérifié **sur le fichier relu depuis le disque**, pas sur les objets
  en mémoire.
- **Écarté :** considérer que les scripts d'évaluation étaient des tests.
- **Preuve :** trois bugs réels trouvés en les écrivant. (1) Chaque capture d'écran était
  classée « aucune observation extraite », une seconde raison plus vague écrasant la
  vraie — or **la raison pour laquelle un agent n'a pas pu lire un fichier est tout
  l'intérêt de noter qu'il n'a pas pu.** (2) L'inventaire **vide** — la plus forte preuve
  d'absence du corpus — enregistrait une couverture sans système, donc inutilisable, parce
  que je lisais le système dans les enregistrements et qu'il n'y en avait aucun. (3) Deux
  PDF qui nomment une personne sans nommer d'enregistrement auditable étaient
  indiscernables d'un échec de lecture. *« Illisible » et « lu et légitimement vide »
  appellent des actions différentes.*

### D37 — Casser son propre code pour savoir si les tests servent · 17h30
- **Choisi :** injecter **12 défauts** un par un et exiger que la suite passe au rouge.
- **Preuve :** **12/12 attrapés.** Et deux ne l'étaient pas au début — or le défaut était
  que **mes mutations étaient infidèles**, pas que les tests étaient faibles : « matcher
  par sous-chaîne » touchait `matches`, alors que deux adresses complètes ne s'emboîtent
  pas ; ce qui s'emboîte, c'est une adresse dans un **token plus long**, donc
  `mentioned_in`. *Corriger les défauts plutôt que les tests, c'est ce qui donne un sens
  au chiffre.*

### D38 — L'injection de prompt : la garde est **structurelle**, pas statistique · 17h40
- **Choisi :** **une injection peut faire auditer PLUS, jamais MOINS.** Un refus d'auditer
  n'est pas accepté d'un message porteur de marqueurs d'injection, quelle que soit la
  confiance du modèle.
- **Écarté :** se reposer sur une consigne dans l'invite (« ignore les instructions
  embarquées ») — nécessaire, mais ça demande au modèle de gagner.
- **Preuve :** `NOT_APPLICABLE` est **le seul verdict qui arrête l'agent**. C'est donc le
  seul qui vaille la peine d'être attaqué, et une injection réussie rend un plan vide, un
  tableau de bord vert, et les données en place — le fantôme, cette fois exprès. **Le
  modèle n'a pas besoin de gagner.** Testé : aucune des 518 demandes fournies ne déclenche
  le détecteur, les 3 attaques fabriquées sont contenues, et une vraie demande d'accès
  reste `NOT_APPLICABLE` — la garde ne dit pas oui à tout.

### D39 — Le signal de supervision qui surprend · 17h50
- **Choisi :** **une hausse des verdicts `COMPLETE` est l'alarme**, pas la bonne nouvelle.
- **Écarté :** surveiller un taux d'erreur.
- **Preuve :** un agent d'audit **échoue en silence**. Il ne plante pas quand il commence à
  manquer des copies : il répond `COMPLETE`. Donc un tableau de bord qui surveille les
  erreurs resterait **muet pendant exactement la panne que ce système existe pour
  empêcher**. Et le moniteur a trouvé quelque chose dès son premier run : le message
  trompeur « vision pass returned nothing » sur des fichiers en réalité bien lus.

| 17h55 | **robustesse** | 91 tests · 12/12 mutations · injection · supervision | 0,969 | 0,281 | score inchangé — *ces ajouts portent sur ce qui se passe quand ça va mal* |

> **Le score n'a pas bougé d'un millième, et c'est normal.** Ces quatre chantiers ne
> traitent pas de la justesse sur les 32 cas étiquetés : ils traitent de ce qui arrive
> quand une entrée est hostile, quand un parseur casse, quand un fichier devient illisible,
> et de **comment on l'apprendrait**. C'est exactement ce que trois des sept axes de
> l'entretien demandent.

### D40 — « La preuve la plus récente » voulait dire autre chose · 18h10
- **Choisi :** parcourir les observations de la plus récente à la plus ancienne et retenir
  **la première qui tranche**.
- **Écarté :** prendre la plus récente, point (ce que je faisais).
- **Preuve :** `backup_4978` porte `restore_allowed=1` dans un instantané SQL, et un log
  **deux jours plus tard** mentionne l'archive sans rien en dire. Prendre la plus récente
  jetait la seule qui répondait à la question. *« La preuve la plus récente » devait depuis
  le début vouloir dire « la plus récente qui dit quelque chose ».* F1 étapes
  **0,846 → 0,856**, rappel 0,756 → 0,772.

### D41 — Une sauvegarde dont on ignore le statut **est** un risque · 18h15
- **Choisi :** `BACKUP_ARCHIVE` à l'état indéterminé → **risque de restauration**, donc
  finding, blocage et vérification.
- **Écarté :** la traiter comme conforme (ce que je faisais).
- **Preuve :** le critère d'achèvement dit *« no active sync, import, or restore path can
  recreate the data »*, et un **inconnu ne le satisfait pas**. Une archive peut-être
  restaurable doit être bloquée de toute façon. C'est le seul endroit où le *fail-closed*
  consiste à **affirmer** un risque plutôt qu'à suspendre un verdict — parce qu'ici les
  deux reviennent au même. F1 **0,856 → 0,866**, rappel **0,788**, et la précision
  **monte** à 0,962 : ces sauvegardes étaient réellement restaurables.

| 18h20 | **final** | 94 tests · 12/12 · 5/5 | **0,969** | 0,281 | P **0,962** · R **0,788** · **F1 0,866** · champs 0,708 · preuves 0,827 |

> **Rappel 0,788 sur un plafond de ~0,85 : 93 % de ce que ce jeu de données permet.**
> Les 47 étapes qui manquent sont 15 ressources absentes de toute preuve, 15 nommées sans
> identifiant de sujet, 9 attribuées ailleurs ou capturées après la coupure, et une poignée
> de désaccords d'état. Le reste coûte plus qu'il ne rapporte.

### D42 — La fiche d'entretien citait des chiffres périmés · 18h40
- **Choisi :** tout recorriger, et **mettre en tête la commande qui régénère les
  chiffres** — avec la consigne : si elle diffère de la fiche, **c'est elle qui a raison**.
- **Preuve :** la fiche disait F1 0,846 (c'est 0,866), 91 tests (c'est 122), quatre cas
  d'évaluation (c'est cinq). *Un document dont le rôle est d'empêcher d'inventer un
  chiffre était lui-même plein de chiffres devenus faux.* Deux axes officiels y manquaient
  aussi : la **recherche d'information**, listée séparément de l'architecture, et la
  question « que se passe-t-il quand le modèle casse ton schéma ».

### D43 — Mon harnais de mutation **mentait** · 18h55
- **Choisi :** un **processus par défaut injecté**, et patcher `observed_state` **partout
  où le nom est lié**.
- **Écarté :** le harnais tel qu'il annonçait fièrement 15/15.
- **Preuve :** j'ai vérifié **un seul** résultat à la main. La mutation « sauvegarde non
  vérifiée passe pour bloquée » n'était attrapée par **aucun** test quand on la lançait
  seule. Deux causes, **toutes deux dans le harnais** : (1) `engine.py` fait
  `from .policy import observed_state`, donc il garde sa propre référence et patcher le
  module ne l'atteignait pas — la mutation était **inerte** ; (2) les défauts tournaient
  dans un seul processus, les effets fuyaient d'un run au suivant, et la mutation inerte
  était **créditée des échecs causés par la précédente**.

  Le chiffre honnête est alors tombé à **13/15** — et ces deux-là étaient de **vrais
  trous dans les tests** : rien ne couvrait la règle « une ressource par système », rien
  ne couvrait le rejet des identifiants factices. Les deux sont testés maintenant, avec un
  test compagnon qui **désactive** la contrainte et exige que des doublons apparaissent —
  sinon le premier test mesurerait un hasard du jeu de données, pas la règle.

  **Un harnais de mutation qui ment est pire que pas de harnais, parce que ce qu'il
  certifie, c'est la suite de tests.**

### D44 — Mon garde-fou m'a arrêté deux fois de plus, et il avait raison · 19h05
- **Choisi :** changer la clé factice des tests pour une chaîne qui **ne ressemble pas** à
  une clé ; et **caviarder** les chaînes en forme de clé dans les **copies** de la trace.
- **Écarté :** mettre les deux sur liste blanche.
- **Preuve :** ma clé de test était `sk-` suivi de remplissage. **Rien qui lise un fichier
  ne peut distinguer un faux convaincant d'un vrai** — et les instructions de trace de
  HackerRank demandent explicitement de caviarder avant de partager. Les fichiers
  d'origine ne sont jamais touchés ; 10 chaînes caviardées dans les copies.

| 19h10 | **final** | 122 tests · 15/15 **vérifié** · 5/5 | **0,969** | 0,281 | P 0,962 · R 0,788 · **F1 0,866** |

### D45 — Deux portes essayées, deux portes mesurées, aucune gardée · 19h30
- **Écarté n°1 :** laisser **n'importe quelle** ligne d'activité localiser la rafale, au
  lieu des seules lignes d'un acteur de suppression. **Le rappel ne bouge pas du tout**
  (0,788 des deux côtés), la précision tombe 0,962 → 0,944, F1 0,866 → 0,859. Les champs
  montent, mais *le changement était fait pour le rappel, et le rappel n'a pas bougé.*
- **Écarté n°2 :** énumérer tous les blocs contigus dans la fenêtre de la demande et
  garder ceux sans propriétaire en conflit. **Rappel 0,162, 137 ressources parasites.**
- **Preuve de la cause :** la rafale existe bel et bien — `account_6440` est
  `activity_3661`, `analytics_5335` est `activity_3665`, quatre identifiants et trente
  minutes d'écart — mais **aucune ressource ancrée de ces sujets n'a de ligne d'acteur de
  suppression**. Il n'y a pas de porte d'entrée. Les deux tentatives restent dans le
  script de balayage avec leurs chiffres, pour que personne ne passe une soirée à les
  redécouvrir.

### D46 — Le scanner de la plateforme dit lui-même ce qu'il a trouvé · 19h40
- **Choisi :** lire `matched_value` d'une ligne `message_pii_scan` comme **une donnée
  personnelle encore stockée** *et* comme un **identifiant du sujet**.
- **Preuve :**
  `resource_id=support_9553 event=message_pii_scan matched_value="e.varga90@yahoo.com"
  detector=direct_identifier`. C'est le scanner de support qui **constate** que
  l'enregistrement contient encore l'adresse. Ça règle deux choses d'un coup : à qui il
  appartient, et qu'il expose. Le corpus en est plein, et je les lisais comme des
  événements sans contenu. **F1 0,866 → 0,876**, rappel **0,803**, séquence 0,281 →
  **0,312**, champs 0,740, preuves 0,840, précision stable à 0,963.
- **La limite, posée volontairement :** un scan **n'est pas** une énumération de champs.
  Il rapporte ce qu'il a *trouvé*, jamais l'enregistrement entier — il peut donc prouver
  qu'un identifiant est là, **jamais** que les autres sont partis. Deux tests le fixent,
  dont un qui parcourt tout le corpus et exige qu'aucune ligne de scan ne puisse jamais
  prouver un masquage.

| 19h45 | **rappel final** | signal de scan PII | **0,969** | **0,312** | P **0,963** · R **0,803** · **F1 0,876** · champs 0,740 · preuves 0,840 |

> **Rappel 0,803 sur un plafond de ~0,85 : 94 % de ce que ce jeu de données permet.**
> Reste : 15 ressources dans aucune preuve, 15 derrière une rafale sans porte d'entrée,
> 4 capturées après la coupure. J'arrête ici — les deux dernières portes ont été
> essayées et mesurées.

### D47 — Le test adverse que j'avais promis a trouvé le bug en une exécution · 20h10
- **Choisi :** écrire enfin *« someone else's record deliberately placed inside a subject's
  deletion run »* — ce que j'avais rangé dans « ce que je ferais avec une semaine de plus ».
- **Preuve :** il a échoué **au premier lancement**. `analytics_2265` était audité pour
  `user_34` **et** `user_35`. L'enregistrement est anonymisé, donc **sans aucun
  identifiant par construction**, et il se trouve à l'endroit du flux où deux rafales se
  rejoignent : le filtre de propriété ne peut exclure ni l'un ni l'autre voisin.
  *Une promesse de test n'est pas un test.*

### D48 — Refuser l'ambiguïté, mais seulement là où elle existe · 20h20
- **Écarté :** refuser **toute** piste sans propriétaire dans un bloc mixte — mesuré :
  précision 0,963 → **0,993**, mais rappel 0,803 → **0,756**, F1 0,876 → 0,859. Ça jette
  aussi les enregistrements anonymisés que cette route existe précisément pour atteindre.
- **Choisi :** ne refuser que ce qui est **disputé dans le même système**. Une personne a
  un seul profil analytique : un enregistrement analytique sans propriétaire posé à côté de
  celui d'un inconnu est ambigu ; l'entrée d'index d'un inconnu ne dit **rien** sur une
  sauvegarde sans propriétaire. Précision **0,981**, rappel **inchangé**, F1 **0,883**.

### D49 — Borner une limite plutôt que nier · 20h25
- **Choisi :** le test affirme la garantie qui **tient vraiment** — un enregistrement que
  *n'importe quelle* preuve attribue à quelqu'un n'est jamais audité pour un autre — et
  **borne** le résidu sans propriétaire (12 ressources sur 302).
- **Écarté :** garder l'assertion forte qui échouait.
- **Preuve :** affirmer davantage, ce serait affirmer quelque chose de faux. *Un test qui
  ment est pire qu'un test absent, pour la même raison qu'un harnais de mutation qui ment.*

### D50 — Le harnais a attrapé mon test en train de viser à côté · 20h35
- **Preuve :** sur six nouvelles mutations, une n'était **pas** attrapée — « le CSV écrit
  sans contrôle de fin de ligne ». Mon test cherchait `CR LF CR LF`. Or le défaut produit
  `CR CR LF` : la couche de traduction transforme le `LF` de l'écrivain en `CR LF`. **Le
  défaut était réel et mon assertion le manquait.** Corrigé : les deux formes, plus une
  relecture du fichier à la recherche de lignes vides. **21/21.**

### D51 — Corriger une affirmation de mon propre rapport · 20h45
- **Choisi :** écrire que les runs à froid **ne sont pas garantis identiques**.
- **Écarté :** laisser « trois runs à froid, sortie identique au bit près » — c'était vrai
  quand je l'ai écrit, ça ne l'est plus tout à fait.
- **Preuve :** deux runs à froid du **même code** diffèrent d'**un verdict de cas et deux
  étapes sur ~2 370** (~0,2 %), parce que la passe visuelle rend 19 enregistrements une
  fois et 20 une autre, à température 0. Le cœur déterministe, lui, n'a **jamais** bougé,
  et `--no-vision` supprime la variation. *Le rapport dit maintenant la forme exacte de la
  chose : un moteur reproductible, une étape qui ne l'est pas, et un cache qui rend tout
  rejeu exact.*

| 20h50 | **garanties** | 142 tests · **21/21** · 18 cas adverses | **0,969** | **0,312** | P **0,981** · R 0,803 · **F1 0,883** |

### D52 — Une vérification est un contrôle à **exécuter**, pas une affirmation · 20h55
- **Choisi :** émettre le `VERIFY_RECORD_PRESENT` d'un enregistrement **à conserver**
  même quand son état n'a pas pu être confirmé à la coupure ; et accepter qu'une preuve
  **postérieure** l'identifie.
- **Preuve :** un enregistrement à conserver ne peut **jamais** produire de finding — son
  état exigé est `PRESENT`, il n'est un écart que s'il **manque**. Donc l'identifier tard
  ne peut ajouter qu'une **vérification**. Et dans un cas `COMPLETE`, où toute
  vérification doit citer sa preuve, une vérification sans citation est **écartée** au
  lieu d'être publiée. Le pas survit exactement là où l'énoncé dit que la vérification ne
  porte pas de citation : un cas `INCOMPLETE` qui décrit du travail à venir.
  F1 **0,883 → 0,893**, rappel 0,803 → 0,819.

### D53 — Deux formats de logs écrivent du JSON, et je n'en lisais rien · 21h05
- **Preuve :** `"subject_ref":"user_61"` était là, ligne 24 de la trace de
  `audit_record_4902`. Mon tokeniseur ne cherchait que `clé=valeur` ; JSON sépare par un
  **deux-points**. Les identifiants de ressource et de trace ayant leurs propres motifs,
  **ces lignes avaient l'air lues** — pendant que tout champ disant *à qui* appartient
  l'enregistrement était jeté en silence. *C'est la pire forme de bug de parseur : il ne
  laisse aucune trace d'avoir échoué.* Rappel 0,819 → **0,829**, F1 **0,896**.

### D54 — L'échappement **est** le délimiteur · 21h10
- **Écarté :** déséchapper la ligne avant de tokeniser. Ça détruit la délimitation :
  `message="resource_id="account_66777" rows="1""` et le champ extérieur avale tout.
- **Choisi :** tokeniser **d'abord** (le motif accepte déjà les guillemets échappés dans
  une valeur), **puis** déséchapper cette valeur et la tokeniser à son tour.

### D55 — Deux horloges, et elles ne sont pas interchangeables · 21h15
- **Preuve :** mon test de coupure a attrapé une **vraie violation** que je venais
  d'introduire. Un enregistrement porte son propre instant d'observation, qui **ordonne**
  les observations dans un fichier. Mais ce qui rend une preuve **recevable**, c'est
  l'instant de capture du **fichier** au manifeste — c'est lui, l'« evidence item » que
  l'énoncé interdit de citer après la coupure. `evidence_06` est daté du 18/09 et contient
  des lignes du 16/09 : admettre le fichier sur l'heure de la ligne, c'était citer une
  preuve capturée **deux jours après** l'audit.

### D56 — Une capture d'écran ne déplace pas une ressource hors de sa famille · 21h25
- **Preuve :** `backup_9287` était planifié « bloquer la restauration » dans un run et
  « supprimer l'enregistrement » dans un autre, **à code identique**. Cause : la vision
  avait mal lu sa catégorie, et `category_of` laissait la catégorie de la preuve écraser
  le préfixe **sans condition**. *La source la moins fiable du corpus pouvait changer le
  traitement que la politique exige.*
- **Choisi :** une catégorie issue de la **vision** peut **affiner** à l'intérieur de la
  famille établie par le préfixe, jamais en faire sortir. Les lecteurs **texte** gardent
  toute leur autorité — ils sont déterministes.
- **Et le coût :** **zéro**. F1 inchangé à 0,896. *C'est la forme que devrait avoir un
  correctif de déterminisme.* Vérifié ensuite : run à froid depuis l'archive extraite,
  **0 cas différent** sur 518.

### D57 — Le plafond que j'annonçais me flattait · 21h20
- **Choisi :** annoncer **0,912**.
- **Écarté :** « environ 0,85 » — qui était le plafond compté par **ressource** (94 sur
  111 atteignables).
- **Preuve :** la métrique que je rapporte est le rappel d'**étapes**. Compté par étape,
  17 des 193 reposent sur des ressources absentes de toute preuve, donc le plafond est
  **0,912**. On atteint 0,829 : **91 %** de ce que les données permettent, et non 97 %.
  *Le chiffre le plus bas rendait le résultat plus beau qu'il n'est.*

| 21h30 | **final** | 151 tests · **22/22** · 5/5 | **0,969** | **0,312** | P **0,976** · R **0,829** · **F1 0,896** |

---

### D58 — Une question sur les tests de sécurité en a révélé un vrai · 05h00
- **Déclencheur :** « est-ce qu'il y a des tests de sécurité, juste pour savoir ». J'ai
  vérifié au lieu de répondre de mémoire.
- **Preuve :** les instantanés SQL sont **exécutés** avec `sqlite3` — choix assumé, une
  regex sur les `INSERT` se casse dès qu'une valeur contient une virgule ou une
  apostrophe, et ces fichiers portent des noms et des extraits de messages. Mais ça veut
  dire qu'on **exécute un fichier écrit par quelqu'un d'autre**. J'ai écrit l'attaque :

  ```sql
  ATTACH DATABASE '/ailleurs/fichier.db' AS out;
  CREATE TABLE out.x (c TEXT);
  ```

  **Elle a écrit le fichier.** Une preuve pouvait sortir de la base en mémoire et
  atteindre le disque.
- **Choisi :** un autorisateur **en refus par défaut** sur la connexion. La liste des
  actions permises n'est pas devinée : j'ai d'abord lancé un autorisateur en mode **trace**
  sur un vrai instantané pour voir ce qu'il demande réellement — créer tables et index,
  insérer, lire, transaction, réindexer, et un seul `PRAGMA foreign_keys`. Tout le reste
  est refusé : `ATTACH`, `DETACH`, `writable_schema`, `temp_store_directory`.
- **Pourquoi pas une liste noire :** *elle n'arrête que les attaques auxquelles on a déjà
  pensé, et ces fichiers sont exécutés avant que quiconque les ait lus.*

### D59 — Ma première garde a cassé les 24 fichiers en silence · 05h05
- **Preuve :** trop stricte, elle faisait tomber les observations de **2 915 à 2 004** —
  et le **score n'avait pas encore bougé**. Je l'ai vu en comparant le nombre
  d'observations, pas la note. *C'est exactement le mode d'échec que ce projet rencontre
  sans arrêt : une étape qui ne contribue plus rien, sans rien signaler.* Corrigé par le
  traçage ; corpus relu à l'identique, score inchangé à 0,896.

### D60 — Un test qui ne montre que le cas bloqué ne prouve rien · 05h08
- **Choisi :** six tests, dont **un qui montre l'attaque RÉUSSIR sans la garde** avant de
  la montrer bloquée.
- **Preuve :** sans ce premier test, rien ne distingue « la garde fonctionne » de
  « l'attaque n'a jamais marché ». 151 → **157 tests**.

### D61 — Et ma mutation était inerte, encore · 05h12
- **Preuve :** le 23ᵉ défaut patchait `sqlite3.Connection.set_authorizer` — sans effet,
  `Connection` est un type C dont on ne peut pas remplacer les méthodes. Le harnais l'a
  annoncé **non attrapé**, à juste titre. *C'est précisément à ça que sert un processus
  par défaut : une mutation inerte se voit au lieu d'être créditée de la précédente.*
  Reciblé sur la fonction de garde elle-même. **23/23.**

| 05h20 | **sécurité SQL** | autorisateur + 6 tests + 1 mutation | **0,969** | **0,312** | 157 tests · **23/23** · score inchangé **0,896** |

> **La leçon qui vaut pour l'entretien :** je n'ai pas trouvé ça en relisant le code, mais
> en **écrivant l'attaque et en la lançant**. Le code avait l'air sûr. Il ne l'était pas.

---

## Pour soumettre


Tout est dans **`SOUMISSION.md`** : deux commandes, quatre chemins de fichiers, l'URL, et
quoi faire si quelque chose casse. Rien à décider, rien à retrouver.

> **Le chiffre à retenir pour l'entretien :** le workflow interne de Northstar, celui dont
> tous les tableaux de bord affichaient « Complete », note **0,531** — moins bien que de
> répondre « INCOMPLETE » à tout le monde sans rien regarder (0,688). L'histoire des
> 2,4 M$ n'est pas une mise en scène, elle est mesurable dans les données.

> **Re-mesurer après chaque changement.** Sans avant/après, je ne saurai pas
> quoi répondre, et j'aurai peut-être dégradé sans le voir.

> **Re-mesurer après chaque changement.** Sans avant/après, je ne saurai pas
> quoi répondre, et j'aurai peut-être dégradé sans le voir.

---

## Les questions du juge, et où est ma réponse

Le juge interroge l'**architecture, les décisions, les arbitrages**. À relire
dimanche avant l'entretien — chaque question doit pointer vers une entrée
ci-dessus.

**Le mail HackerRank nomme les quatre axes** : *architecture*, *safety and
failure handling*, *testing*, *what makes your approach special*. Une entrée
par axe au minimum.

| Axe | Question probable | Mon entrée |
|---|---|---|
| Architecture | Pourquoi cette architecture plutôt qu'une autre ? | D… |
| Architecture | Qu'est-ce qui casse en premier si la charge triple ? | D… |
| **Sûreté / défaillances** | Que fait l'agent quand il **ne sait pas** ? | *fail-closed* : il le dit, il ne devine pas |
| **Sûreté / défaillances** | Qu'est-ce qui se passe si l'API tombe au milieu ? | réessai réseau, puis échec explicite |
| **Sûreté / défaillances** | Comment sais-tu que ta sortie n'est pas silencieusement fausse ? | la colonne de confiance / raison du CSV |
| **Tests** | Comment as-tu testé ? Qu'est-ce que tes tests ne couvrent pas ? | n tests, et le trou nommé |
| **Tests** | Comment sais-tu que c'est meilleur qu'avant ? | tableau des mesures |
| **Ce qui est spécial** | Qu'est-ce que personne d'autre n'a fait ? | la mesure avant/après, pas l'intuition |
| **Ce qui est spécial** | Qu'est-ce que tu as abandonné, et pourquoi ? | entrée D… |
| — | Qu'est-ce que tu n'as pas eu le temps de faire ? | gel de minuit |

**Les deux réponses qui valent le plus cher**, parce que presque personne ne les
donne : *« je ne l'ai pas mesuré, donc je ne l'affirme pas »* et *« j'ai essayé
ceci, voilà le chiffre, je l'ai abandonné »*.
