# OSM Workshop 2026 — Research Like a Software Engineer

> **Organizing Your Projects Like Applications**

A workshop demonstrating how to combine OpenStreetMap data, German census data, and open-source routing tools to answer real geospatial research questions — built and run like a proper software project.

The central research question explored in this workshop:

> *What percentage of residents in a German city live within a 15-minute walk of a park or greenspace?*

---

## Workshop slides

The slides for this workshop are published at:
**<https://travishathaway.github.io/osm-workshop-2026>**

They walk through the full arc of the workshop: setting up the environment, understanding the tools, discovering the research question, building the project structure, running the analysis, and interpreting the results.

---

## Repository structure

```
.
├── app/        # Parkalyzer — the Python CLI application built during the workshop
└── slides/     # Quarto reveal.js presentation (index.qmd)
```

See [`app/README.md`](app/README.md) for full setup and usage instructions for the CLI.

---

## What you will need

The workshop uses a composable stack of open-source tools, mostly managed through [pixi](https://prefix.dev):

| Tool | Role |
|---|---|
| [PostgreSQL](https://www.postgresql.org) + [PostGIS](https://postgis.net) | Spatial database for OSM and census data |
| [osmprj](https://github.com/travishathaway/osmprj) | Import and schema management for OSM PBF data |
| [zensus2pgsql](https://github.com/travishathaway/zensus2pgsql) | Import German census grid data into PostgreSQL |
| [openrouteservice](https://openrouteservice.org) | Self-hosted walking route calculation |
| [ors-launcher](https://github.com/travishathaway/ors-launcher) | Convenience wrapper to run openrouteservice locally |
| [pgAdmin](https://www.pgadmin.org) | Visual database exploration |
| [QGIS](https://qgis.org) | Spatial data visualisation |

---

## Quick start

Clone the repository and navigate to the `app/` directory:

```bash
git clone git@github.com:travishathaway/osm-workshop-2026.git
cd osm-workshop-2026/app/

# Start a shell with all dependencies installed
pixi shell -e dev
```

Then run the setup script to start PostgreSQL, import OSM and census data, and launch openrouteservice:

```bash
bash scripts/dev-setup.sh
source env.sh
```

Full step-by-step instructions are in [`app/README.md`](app/README.md).

---

## Adapting this workshop

This workshop is designed to be reused and adapted. You can swap the city (the default is Brandenburg / Berlin), substitute a different OSM region from [Geofabrik](https://download.geofabrik.de), or extend the analysis with additional greenspace categories.

If you adapt this material for your own workshop or course, please keep the license notice intact and share any modifications under the same terms (see below).

---

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

You are free to use, modify, and redistribute this material — including for teaching and research purposes — provided that:

- Modifications are released under the same AGPL-3.0 license.
- The source of any publicly accessible service built from this code is made available.

See the [`LICENSE`](LICENSE) file for the full terms.
