# Логотип для бота «Персональная сказка»

Промты ниже можно вставлять в ChatGPT (создание изображений), Gemini, Midjourney, Flux, Ideogram и т. п.
Лучше всего модели понимают **английский** — поэтому сами промты на английском, а пояснения на русском.

## Что нужно знать про аватарку бота

* Telegram показывает её **кругом** — всё важное держите в центре (в запасе по краям ~15 %).
* Не нужно текста и букв: на маленьком размере он не читается, а нейросети часто делают в нём ошибки.
* Размер: квадрат 1024×1024 (от 512×512), PNG или JPG.
* Как поставить: в Telegram откройте **@BotFather** → `/setuserpic` → выберите бота → отправьте картинку.
* Временный логотип уже лежит рядом: `logo_512.png` (и `logo.svg`) — его можно поставить хоть сейчас.

## Вариант 1 — эмблема (рекомендую, совпадает с дизайном приложения)

```
Square app icon logo for a children's personalized fairy-tale Telegram bot. A glowing open storybook floating in the center, warm golden light rising from its pages, a few sparkling four-point stars and a golden crescent moon above it. Soft Tien Shan mountains and a tiny white Kyrgyz yurt with a glowing door on the horizon. Night-sky gradient from deep indigo to violet, warm coral glow at the horizon. Modern flat vector illustration with soft shading and rounded friendly shapes, storybook gouache feel, clean and minimal, centered composition with generous padding so it survives a circular crop. No text, no letters, no watermark, no border. 1:1, 1024x1024.
```

## Вариант 2 — милый персонаж-талисман

```
Square app icon, cute friendly baby lamb with a fluffy cream wool and big kind eyes, wearing a tiny golden nightcap, hugging a small glowing storybook; a crescent moon and sparkling stars behind it on a deep indigo-to-violet night sky with soft coral glow at the bottom. Warm, cozy, gentle children's picture-book style, soft gouache textures, rounded shapes, high contrast, centered with generous padding for a circular crop. No text, no letters, no watermark. 1:1, 1024x1024.
```

(Ягнёнок — «безопасный» герой и для исламского режима, и для кыргызского контекста. Если хочется другого животного: sheep → little horse / owl / camel.)

## Вариант 3 — простой знак (для печати и маленьких размеров)

```
Minimalist flat vector logo mark: an open book whose pages form a crescent moon, with one golden four-point star above it, on a solid deep indigo circle background. Only three colors: indigo (#1b1747), cream (#fbf6ea) and gold (#ffc24d). Very simple geometric shapes, perfectly centered, large safe margins, no gradients, no text, no letters, no shadows. 1:1, 1024x1024.
```

## Если генератор поддерживает «негативный промт»

```
text, letters, words, watermark, signature, border, frame, realistic photo, scary, dark horror, cluttered, blurry, low contrast, extra fingers
```

## Фирменные цвета приложения (чтобы всё выглядело одинаково)

| Цвет | Код |
|---|---|
| Ночное небо | `#1b1747` → `#2e2780` |
| Фиолетовый (кнопки) | `#6b4cff` |
| Золото | `#ffc24d` |
| Коралл | `#ff7b6b` |
| Бумага | `#fbf6ea` |

## Советы

1. Сгенерируйте 4–6 картинок, выберите самую читаемую **в маленьком размере** (уменьшите до 64 пикселей — узнаётся ли?).
2. Если в картинке случайно появились буквы, попросите «remove all text» или перегенерируйте.
3. Проверьте круглую обрезку: загрузите в @BotFather и посмотрите на бота в списке чатов.
