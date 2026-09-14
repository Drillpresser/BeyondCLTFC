#!/usr/bin/env Rscript
# Independent cross-source career read via worldfootballR (R).
#
# worldfootballR is a mature, well-maintained scraper for FBref, Transfermarkt,
# Understat and FotMob. We use it as an *independent lineage* for the same facts
# other fetchers gather (season apps/goals/minutes + bio), so build_players.py can
# put them side by side and surface disagreements. It reuses the player IDs/URLs
# already resolved by fetch_fbref.py and fetch_transfermarkt.py, so no new
# name-resolution logic lives here.
#
# Run from scripts/ (the Python wrapper does this):  Rscript fetch_worldfootball.R
# Writes: data/raw/worldfootball.json   name -> {bio, seasons:[...]}

suppressMessages({
  ok <- require(worldfootballR) && require(jsonlite)
})
if (!ok) {
  message("worldfootballR / jsonlite not installed; skipping. ",
          "Install with: install.packages(c('worldfootballR','jsonlite'))")
  quit(status = 0)
}

raw_dir <- file.path("..", "data", "raw")
read_ids <- function(f) {
  p <- file.path(raw_dir, f)
  if (file.exists(p)) jsonlite::fromJSON(p, simplifyVector = FALSE) else list()
}

fbref_ids <- read_ids("fbref_player_ids.json")
tm_ids    <- read_ids("transfermarkt_ids.json")
players   <- union(names(fbref_ids), names(tm_ids))
message(sprintf("worldfootballR cross-read for %d player(s).", length(players)))

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

out <- list()
for (nm in players) {
  rec <- list(bio = NULL, seasons = list())

  fb <- fbref_ids[[nm]]
  if (!is.null(fb) && !is.null(fb$url)) {
    tryCatch({
      df <- fb_player_season_stats(fb$url, stat_type = "standard")
      if (!is.null(df) && nrow(df) > 0) {
        seasons <- lapply(seq_len(nrow(df)), function(i) {
          list(
            season  = as_int(substr(as.character(pick(df, "^Season")[i]), 1, 4)),
            season_label = as.character(pick(df, "^Season")[i]),
            club    = as.character(pick(df, "^Squad")[i]),
            comp    = as.character(pick(df, "^Comp")[i]),
            apps    = as_int(pick(df, c("^MP", "Playing.*MP", "Matches"))[i]),
            minutes = as_int(pick(df, c("^Min", "Minutes"))[i]),
            goals   = as_int(pick(df, c("^Gls", "^Goals"))[i]),
            assists = as_int(pick(df, c("^Ast", "^Assists"))[i])
          )
        })
        # Drop rows without a parseable season (totals / blank separators).
        rec$seasons <- Filter(function(s) !is.na(s$season), seasons)
      }
    }, error = function(e) message(sprintf("  fbref error %s: %s", nm, conditionMessage(e))))
  }

  tm <- tm_ids[[nm]]
  if (!is.null(tm)) {
    tryCatch({
      url <- sprintf("https://www.transfermarkt.com/-/profil/spieler/%s", tm)
      bio <- tm_player_bio(url)
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
  message(sprintf("  %s: %d season rows", nm, length(rec$seasons)))
}

jsonlite::write_json(out, file.path(raw_dir, "worldfootball.json"),
                     auto_unbox = TRUE, pretty = TRUE, null = "null", na = "null")
message("worldfootballR cross-read complete.")
