#!/usr/bin/env Rscript
# Independent cross-source career read via worldfootballR (R).
#
# worldfootballR is a mature scraper for FBref, Transfermarkt, Understat and
# FotMob. We use it as an *independent lineage* for the same facts other fetchers
# gather (season apps/goals/minutes + bio), so build_players.py can put them side
# by side and surface disagreements.
#
# Player resolution is self-contained: worldfootballR::player_dictionary_mapping()
# is a large name -> {FBref URL, Transfermarkt URL} table, so we don't depend on
# the other fetchers' ID caches. Matches are made on accent-stripped names.
#
# NOTE: FBref sits behind Cloudflare and blocks datacenter IPs — this generally
# works from a residential IP (local runs) but is best-effort in CI.
#
# Run from scripts/ (the Python wrapper does this):  Rscript fetch_worldfootball.R
# Writes:
#   data/raw/worldfootball_ids.json  name -> {fbref, tmarkt} (resolved URL cache)
#   data/raw/worldfootball.json      name -> {bio, seasons:[...]}

suppressMessages({
  ok <- require(worldfootballR) && require(jsonlite)
})
if (!ok) {
  message("worldfootballR / jsonlite not installed; skipping. ",
          "Install with: install.packages(c('worldfootballR','jsonlite'))")
  quit(status = 0)
}

raw_dir <- file.path("..", "data", "raw")
read_json_or <- function(f, default) {
  p <- file.path(raw_dir, f)
  if (file.exists(p)) jsonlite::fromJSON(p, simplifyVector = FALSE) else default
}

use_tm <- identical(Sys.getenv("ENABLE_TRANSFERMARKT"), "1")

# --- roster ---------------------------------------------------------------
asa_path <- file.path(raw_dir, "asa_players.json")
if (!file.exists(asa_path)) {
  message("asa_players.json missing; run fetch_asa.py first. Skipping.")
  quit(status = 0)
}
asa <- jsonlite::fromJSON(asa_path)
player_names <- sort(unique(asa$player_name))
message(sprintf("worldfootballR cross-read for %d player(s).", length(player_names)))

norm <- function(x) {
  x <- iconv(x, to = "ASCII//TRANSLIT")           # strip accents (Ortíz -> Ortiz)
  tolower(trimws(gsub("[^A-Za-z ]", "", x)))
}

# --- resolve name -> FBref / Transfermarkt URLs via the dictionary --------
ids <- list()
map <- tryCatch(player_dictionary_mapping(), error = function(e) {
  message(sprintf("  could not load player dictionary: %s", conditionMessage(e)))
  NULL
})
if (!is.null(map) && nrow(map) > 0) {
  map$._key <- norm(map$PlayerFBref)
  for (nm in player_names) {
    hit <- map[map$._key == norm(nm), , drop = FALSE]
    if (nrow(hit) > 0) {
      ids[[nm]] <- list(fbref = hit$UrlFBref[1], tmarkt = hit$UrlTmarkt[1])
    }
  }
}
message(sprintf("  matched %d/%d players in the dictionary.", length(ids), length(player_names)))
jsonlite::write_json(ids, file.path(raw_dir, "worldfootball_ids.json"),
                     auto_unbox = TRUE, pretty = TRUE, null = "null")

# Pick the first column whose name matches any pattern (FBref column names vary
# between worldfootballR versions, so match defensively rather than hard-code).
pick <- function(df, patterns) {
  for (p in patterns) {
    hit <- grep(p, names(df), value = TRUE, ignore.case = TRUE)
    if (length(hit)) return(df[[hit[1]]])
  }
  rep(NA, nrow(df))
}
as_int <- function(x) suppressWarnings(as.integer(gsub("[^0-9]", "", as.character(x))))

# --- pull stats + bio -----------------------------------------------------
out <- list()
for (nm in player_names) {
  rec <- list(bio = NULL, seasons = list())
  ref <- ids[[nm]]

  if (!is.null(ref) && !is.null(ref$fbref) && nzchar(ref$fbref)) {
    tryCatch({
      df <- fb_player_season_stats(ref$fbref, stat_type = "standard")
      if (!is.null(df) && nrow(df) > 0) {
        seasons <- lapply(seq_len(nrow(df)), function(i) {
          list(
            season       = as_int(substr(as.character(pick(df, "^Season")[i]), 1, 4)),
            season_label = as.character(pick(df, "^Season")[i]),
            club         = as.character(pick(df, c("^Squad$", "^Squad"))[i]),
            comp         = as.character(pick(df, c("^Comp$", "^Comp"))[i]),
            apps         = as_int(pick(df, c("^MP$", "^MP_", "Matches", "^MP"))[i]),
            minutes      = as_int(pick(df, c("^Min$", "^Min_Playing", "Minutes", "^Min"))[i]),
            goals        = as_int(pick(df, c("^Gls$", "^Gls_", "^Goals", "^Gls"))[i]),
            assists      = as_int(pick(df, c("^Ast$", "^Ast_", "^Assists", "^Ast"))[i])
          )
        })
        rec$seasons <- Filter(function(s) !is.na(s$season), seasons)
      }
    }, error = function(e) message(sprintf("  fbref error %s: %s", nm, conditionMessage(e))))
  }

  # Transfermarkt 403s the home server's IP after a burst, so bios are opt-in,
  # same switch as fetch_transfermarkt.py (see server/README.md).
  if (use_tm && !is.null(ref) && !is.null(ref$tmarkt) && nzchar(ref$tmarkt)) {
    tryCatch({
      bio <- tm_player_bio(ref$tmarkt)
      if (!is.null(bio) && nrow(bio) > 0) {
        rec$bio <- list(
          birth_date  = as.character(pick(bio, c("date_of_birth", "born"))[1]),
          nationality = as.character(pick(bio, c("citizenship", "nationality"))[1]),
          position    = as.character(pick(bio, "position")[1]),
          height      = as.character(pick(bio, "height")[1])
        )
      }
    }, error = function(e) message(sprintf("  tm error %s: %s", nm, conditionMessage(e))))
  }

  out[[nm]] <- rec
  message(sprintf("  %s: %d season rows%s", nm, length(rec$seasons),
                  if (is.null(ref)) " (unmatched)" else ""))
}

jsonlite::write_json(out, file.path(raw_dir, "worldfootball.json"),
                     auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null")
message("worldfootballR cross-read complete.")
