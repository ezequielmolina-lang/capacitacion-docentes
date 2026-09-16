# Eligiendo Mi Camino · edición Colombia

Demostración de la plataforma de orientación vocacional adaptada a Colombia, para
la conversación con el Ministerio de Educación Nacional. No es la versión de
producción: es el recorrido completo de las doce sesiones con datos colombianos
para que se pueda ver y probar.

**En vivo:** https://eligiendomicamino.org/colombia/

## De dónde salen las cifras

| Qué | Fuente |
|---|---|
| Ocupación, ni estudia ni trabaja, informalidad | DANE, Gran Encuesta Integrada de Hogares, trimestre móvil mayo a julio de 2026 |
| Tránsito inmediato a la educación superior y matrícula | MEN, SNIES, archivo Perfil Nacional con corte al 31 de mayo de 2026 |
| Ingreso de recién graduados | MEN, Observatorio Laboral para la Educación, corte 2023 |
| Vacantes por ocupación | SENA, Agencia Pública de Empleo, abril a junio de 2026 |
| Salario mínimo | Decreto 1469 de 2025, ratificado transitoriamente por el Decreto 159 de 2026 |

Tres advertencias que la propia página repite, porque sin ellas el dato engaña:

- El DANE no publica informalidad por grupo de edad. La cifra que se muestra es
  de todos los ocupados del país y está rotulada así.
- La lista de vacantes del SENA deja fuera el Nivel A, 33.873 vacantes
  profesionales que esa fuente no desagrega. Sin decirlo, un estudiante concluye
  que no hay demanda de profesionales, y es falso.
- Los salarios por ocupación son una referencia de orden de magnitud: se reescaló
  la estructura del Perú y se ancló a la mediana del ingreso base de cotización
  del OLE. No son cifras oficiales por ocupación.

## Cómo se genera

La edición se construye desde la fuente prístina del Perú, así que se puede
volver a correr entera y cada paso es auditable. En `Downloads\eligiendo-mi-camino-colombia\`:

    python transform.py     # estructura: instituciones, empresas, universidades
    python fill_data.py     # cifras colombianas, rutas, mitos, mascota
    node build.mjs          # compila el JSX y fija React y Tailwind en vendor/
    npx tailwindcss -c tailwind.config.js -i input.css -o vendor/tailwind.css --minify

El último paso importa: la versión anterior compilaba JSX en el navegador con
`@babel/standalone` desde un CDN. Cuando ese paquete cambió de versión mayor, la
página quedó en blanco sin que nadie tocara el código.

La mascota es **Tato**, un oso de anteojos, el oso andino que vive en Colombia.
