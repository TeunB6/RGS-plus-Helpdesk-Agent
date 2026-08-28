---
name: rgsplus-praktijkantwoorden
description: Answers to questions the RGS+ helpdesk gets repeatedly that are NOT in the Confluence manual. Distilled from resolved customer tickets. Read this alongside rgsplus-handleiding — together they are what the helpdesk actually knows.
version: 1.0.0
author: UPPR
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Support, Knowledge Base, RGS+]
---

# RGS+ — praktijkantwoorden

> Distilled from **128 resolved customer tickets** in Jira project HELP, 2025–2026.
> These are answers RGS+ staff have given repeatedly and which are **not written down**
> anywhere in the manual. See `RGSPLUS-SAM-11-DOCUMENTATION-GAPS.md` for the analysis.

## How to use this

- The manual (`rgsplus-handleiding`) is the primary source. **This file covers what the
  manual does not.** The largest gaps are the mobile app and reports/printing.
- **Cite it differently.** These answers come from helpdesk practice, not a manual page, so
  there is no URL to link. Say *"volgens de helpdesk"* rather than inventing a page reference.
- **Where this and the manual disagree, the manual wins**, and say so.
- Everything here has been anonymised. It contains no customer names, addresses, complex
  numbers or credentials, and nothing tenant-specific. Keep it that way.

⚠️ **What is deliberately NOT here:** answers to bugs that were fixed in code
(*"de storing is opgelost"*). Those describe behaviour that no longer exists and would be
worse than no answer at all. 72 tickets were excluded on that basis.

---

## Mobiele app / inspectie-app

**Welk adres gebruik ik op mijn telefoon?**
Op de pc: `v3.rgsplus.nl`. Op mobiel: **`m.rgsplus.nl`**.

**Waarom is er geen echte app in de App Store?**
Het is een web-app. Maak vanuit de browser een snelkoppeling naar je startscherm — die wordt
op het toestel als app weergegeven. Let op: pushmeldingen zijn op Apple-toestellen niet
mogelijk.

**Kan een monteur hoeveelheden aanpassen in de mobiele app?**
Nee. In de mobiele app kun je de **structuur niet wijzigen**, dus ook geen hoeveelheden.
Wel kan de monteur een hoeveelheid ingeven bij een **item (gebrek)**, of in de **labels van
een laag** (hoofdstuk of dakvlak) als daar een label voor is aangemaakt. Wie de structuur
zelf moet aanpassen, gebruikt de gewone applicatie, bijvoorbeeld op een iPad.

**Tip voor tablets:** Chrome werkt het beste, en je kunt een browsertabblad dupliceren zodat
je inspectie en structuur naast elkaar open hebt.

**Een inspecteur kan onze eigen inspectielijsten niet kiezen bij een object van een andere
regievoerder.**
Dat klopt en is een bekende beperking op mobiel. **Workaround:** zet de inspectie op de
desktop klaar; de inspecteur werkt hem daarna op mobiel af.

**Kan ik zien welke inspecties aan welke inspecteur zijn toegewezen?**
Nee, dat is er niet. Wat wel bestaat zijn de **statussen** — *in uitvoering*, *concept*,
*definitief* — waarmee je kunt zien waar een inspectie staat.

---

## Rapporten & printen

**Waarom duurt mijn rapport zo lang?**
Rapporten in de **eerste tabel met de status [bezig]** worden **op de achtergrond
gegenereerd**. Dat kan even duren — daarom gebeurt het op de achtergrond. Het *downloaden*
zelf (de downloadknop in de onderste tabel) gaat wel snel. Een rapport dat "hangt" is dus
meestal nog bezig.

**Waarom staat mijn foto op de verkeerde plek in het rapport?**
Het **label** van de foto bepaalt waar hij terechtkomt:
- label **`plattegrond`** → komt in de rapportage onder plattegrond
- label **`objectfoto`** → komt op het voorblad; is die er niet, dan wordt de eerste foto
  gebruikt

Foto's die ooit als plattegrond zijn gemarkeerd, blijven dat.

**Kan ik kolommen uit een NEN-rapport weglaten?**
Nee. De tabel heeft een vaste structuur met vaste kolommen; die zijn niet los uit te zetten.

**Ons rapport print altijd álle meetplaatsen, dat wil ik niet.**
Bij een **maatwerkrapport** (bijvoorbeeld dat van een samenwerkingsverband) ligt de opzet
vast zoals destijds afgesproken. Wijzigen kan, maar dan moet het verzoek van de overkoepelende
organisatie komen — het geldt dan namelijk voor alle deelnemers.

**Twee opdrachtgevers op één rapport?**
Dat kan en is soms de bedoeling: bijvoorbeeld de VvE als eigenaar van het object én de
beheerder die de inspectieopdracht geeft. Beide opdrachtgevers komen onder elkaar in het
rapport te staan.

---

## Gebruikers & rechten

**Een nieuwe gebruiker heeft geen e-mail gekregen.**
Laat hem inloggen via `v3.rgsplus.nl` en op **"wachtwoord vergeten"** klikken. Hij krijgt dan
een nieuwe link, die **binnen 5 minuten** gebruikt moet worden. Controleer ook of de gebruiker
daadwerkelijk een **rol** heeft gekregen — zonder rol gaat er niets uit.

**Een gebruiker kan geen foto toevoegen aan de objectinformatie.**
Dat hangt aan de rol. Een gebruiker met de rol **inspecteur** kan de algemene objectinformatie
alleen ráádplegen. Ga naar *Gebruikers*, klik op het pennetje achter die gebruiker, en wijzig
de **rol van inspecteur naar gebruiker** — die mag wel een foto toevoegen.

> Dit is het patroon achter veel "het werkt niet"-meldingen: de functie bestaat, maar de rol
> van die gebruiker mag hem niet zien. Vraag bij twijfel welke rol iemand heeft.

**Hoe werkt de inlogcode / tweestapsverificatie?**
Dat is 2FA. Koppel een authenticator-app (bijvoorbeeld Google Authenticator) en neem bij het
inloggen de code daaruit over.

**Hoe ontkoppel ik een bedrijf dat geen partner meer is?**
Open het object of complex, ga naar **Team**, en verwijder het bedrijf daar. Er is geen snelle
manier om dat in bulk te doen — het gaat per object. Zodra het bedrijf ontkoppeld is, zien zij
dat complex niet meer in hun overzicht.

**Hoe lang blijf ik ingelogd?**
Na **10 uur** moet je opnieuw inloggen, en na **2 uur inactiviteit**. Dat is voor iedereen
gelijk. Word je veel vaker uitgelogd, dan ligt dat vrijwel altijd aan de browser of het
apparaat, niet aan RGS+.

---

## Excel-import

> Voor een concreet bestand: gebruik **`import_validate_file`**. Die leest de `uitleg`-tab van
> het sjabloon en zegt precies welke cel fout is *en wat er zou gebeuren*. De importer meldt
> fouten namelijk niet zelf.

**Waar haal ik het importsjabloon vandaan?**
Klik bij de structuur op **[importeren]**; daar staat ook een knop **download template**. In
dat sjabloon staat per kolom uitgelegd wat verplicht is.

**Een export is meteen een importsjabloon.** Exporteer je bijvoorbeeld de elementen, dan kun
je datzelfde bestand aangevuld weer importeren.

**Veelvoorkomende oorzaken van een mislukte import:**
- **`hvh` (hoeveelheid) ontbreekt** — verplicht. Weet je de hoeveelheid niet, zet er dan `0`
  in; er moet een getal staan.
- **`vhe` (verhuurbare eenheden) leeg of tekst** — verplicht en numeriek. Bij utiliteit
  doorgaans `1`, bij een complex woningen vaak meer.
- **`maatregel` leeg** — verplicht.
- **Kolomvolgorde** wijkt af van het sjabloon.
- **Een verkeerd genoemde kolom**, bijvoorbeeld `variant.naam` waar `naam` wordt verwacht.
- De kolom **`id`** mag je leeglaten of helemaal weglaten.

**Een scenario vullen vanuit Excel.**
Exporteer een bestaand scenario naar Excel — je hebt daarvoor de **maatregel-export vanuit het
scenario-overzicht** nodig, *niet* de MJOB-export vanuit het scenario zelf. Dat bestand kun je
importeren. Voor een kopie van een bestaand scenario of een import uit een calculatiepakket is
**XML** het advies: de Excel-import bevat niet alle gegevens en kan afwijken door
afrondingsverschillen.

**Een Excel in de structuur importeren** kan bij *structuur* (geel); daarna maak je een
scenario aan op basis van die structuur.

---

## Koppelingen & import uit andere pakketten

**Kan ik een Gilde-XML importeren?**
Als klant kun je op dit moment alleen de **RGS-XML** importeren. Gilde-XML kan alleen door
RGS+ zelf worden ingelezen — stuur het bestand en het doelobject naar de helpdesk. Krijg je
foutmeldingen bij een Gilde-XML, dan is dat verwacht gedrag en niet iets aan jouw bestand.

**Gilde-import: hoeveel lagen worden ondersteund?**
De opties zijn per schema verschillend: sommige zijn bedoeld voor **twee lagen**, andere voor
**één laag**. **Drie lagen wordt niet ondersteund.**

---

## Inspectie — inrichting

**Waarom zijn er geen keuzeopties (groen / geel / rood) bij een inspectie-item?**
Welke stadia je krijgt, hangt af van de **methode** en van wat er in de **inspectielijst** is
ingevuld. Staat er bij dat item niets ingevuld, dan zijn er ook geen opties. Dit wordt beheerd
in de **stamgegevens**, meestal door één beheerder binnen de organisatie. Een bestaande lijst
is bij te werken; reeds uitgevoerde inspecties blijven behouden.

**Waarom hebben sommige elementen geen inspectie-items?**
Er moet een **koppeling** zijn tussen elementgroep en inspectiegroep: elementen van groep A
worden geïnspecteerd op de items van groep A. Zitten je elementen in een groep waarvoor de
lijst geen items heeft, dan blijven ze leeg.

---

## Wat hier (nog) niet in staat

Deze eerste versie dekt de onderwerpen met de grootste gaten: mobiel, rapporten, rechten,
import en koppelingen. **Inspectie-uitvoering, scenario/MJOB, objecten en prijzenboek zijn nog
niet volledig verwerkt** — daarvoor is een tweede leesronde over de tickets nodig.

Staat het antwoord hier niet en ook niet in de handleiding, dan is het **niet gedocumenteerd**.
Zeg dat eerlijk en schaal op; verzin geen menupad.
