# SwimZH Icon Composer source

Canvas: 1024 x 1024 px. Import the SVG files in numeric order, back to front.

The source artwork deliberately contains no mask, blur, shadow, refraction,
translucency, specular highlight, or background gradient. Apply those in Apple
Icon Composer so the system can render the icon dynamically across Default,
Dark, Clear, and Tinted appearances.

Suggested setup:

1. Set the Icon Composer background to a two-stop blue gradient: `#0878F5` at
   the upper left and `#003A91` at the lower right.
2. Import `01-wave-back.svg`, `02-wave-front.svg`, and `03-swimmer.svg` in that
   order.
3. Keep the two wave layers in one Combined group. Start with Automatic
   specular highlights and restrained refraction/translucency.
4. Keep the swimmer in its own group so it remains the strongest, clearest
   element at small sizes.
5. Preview Default, Dark, Clear, and Tinted appearances at 64 px and 32 px,
   then tune effects in Icon Composer rather than editing the source shapes.

Apple references:

- https://developer.apple.com/design/human-interface-guidelines/app-icons
- https://developer.apple.com/documentation/xcode/creating-your-app-icon-using-icon-composer
- https://developer.apple.com/design/resources/
