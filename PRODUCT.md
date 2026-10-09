# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack
Plain static HTML/CSS/JS (no build step), one page served by the Python app; runs inside a Telegram Mini App webview on phones.

## Users
Parents (and relatives buying a gift) in Kyrgyzstan, mostly on a phone inside Telegram, reading Russian or Kyrgyz. They open the bot, answer a short questionnaire about their child (3–9 years), and wait for a finished PDF book. Some want an Islamic-values mode. Confirmed with the owner (this session).

## Product Purpose
A Telegram bot and Mini App that writes and illustrates a personalized children's fairy-tale book (cover, dedication, 8 illustrated pages, closing page) with the child as the hero, delivered as a PDF in the chat. Price 499 som, paid by bank-QR transfer confirmed manually by the owner. Success: a parent finishes the questionnaire, pays, and receives a book they want to show or print.

## Positioning
A fairy tale written about one specific child, set in Kyrgyz landscapes and customs (Tien Shan, jailoo, yurt, Issyk-Kul, Silk Road), in Russian or Kyrgyz, with an optional Islamic mode. A generic story-app cannot copy the local setting, the language, or the manual QR-payment ritual.

## Operating Context
Telegram Mini App on iOS/Android (360–430 px wide), light or dark Telegram theme. Flow: welcome, 12-step questionnaire (one question per screen, optional child photo), payment screen with the owner's QR and receipt upload, waiting screen with live page previews, result viewer with PDF download and a feedback block. A separate owner-only admin area (receipts to confirm or reject, QR image, price, instruction text).

## Capabilities and Constraints
UI language Russian (Kyrgyz book text supported). Must follow Telegram theme variables for background and text (light/dark). Back button, haptics, safe areas via Telegram WebApp API. Questionnaire order and copy stay as they are unless the owner says otherwise (owner: everything may change). No payment-system integration: manual QR transfer only. Photo upload is a camera or gallery file input. Fonts and art must be self-hosted; no external requests besides telegram.org script.

## Brand Commitments
Name «Персональная сказка». Existing logo files live in branding/ (night-sky yurt). The owner dislikes the current look: violet gradient buttons, emoji used as icons, identical rounded plates, and the current scene illustrations («как у ИИ»). The result must not feel childish and must not look like everyone else's template; it needs real Kyrgyz character. Everything else may be replaced.

## Evidence on Hand
Real example book «Артём и маленький Топик» in webapp/img (book-cover.jpg, book-p2.jpg, book-p4.jpg, book-p6.jpg); the child's photo is used with the owner's consent. No testimonials, customer counts, or press: none may be invented.

## Product Principles
1. The parent should finish in under two minutes: one question per screen, nothing decorative that slows a tap.
2. The book is the proof: show real pages early and let them carry the emotion.
3. Local first: Kyrgyz place, language, and craft are the identity, not a theme skin.
4. Calm trust at the payment and photo steps: say plainly what happens to money and the child's photo.
5. Honest states: waiting, paid-check, errors name the problem and the next step.

## Accessibility & Inclusion
Text contrast at least 4.5:1, tap targets at least 44 px, works at 320 px width, respects reduced motion. Islamic mode and Kyrgyz language users are first-class.
