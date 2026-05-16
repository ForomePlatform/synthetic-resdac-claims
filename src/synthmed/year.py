"""Generate one calendar year worth of FTS-described DAT files."""

from __future__ import annotations

from os import listdir
from os.path import isfile, join
from pathlib import Path

import dorieh.cms.fts2yaml as f2y
import numpy as np
import pandas as pd

from synthmed.columns import (
    char_generation,
    date_generation,
    number_generation,
)


def list_fts_files(input_dir: Path | str) -> list[str]:
    """Return all ``*.fts`` files in ``input_dir`` (non-recursive)."""
    files = [f for f in listdir(input_dir) if isfile(join(input_dir, f))]
    return [f for f in files if f.endswith(".fts")]


def generate_year_files(
    input_dir: Path | str,
    output_dir: Path | str,
    year: int | str,
    base: pd.DataFrame,
    medpar: pd.DataFrame,
) -> None:
    """For every FTS schema in ``input_dir``, emit a matching DAT file."""
    start_date = pd.to_datetime(f"{year}-01-01")
    end_date = pd.to_datetime(f"{year}-12-31")
    prev_dataframes: list[pd.DataFrame] = []

    ftsfiles = list_fts_files(input_dir)
    if ftsfiles and "medpar" in ftsfiles[0].lower():
        ftsfiles.reverse()

    for transfer_file in ftsfiles:
        t = f2y.mcr_type(transfer_file)
        fts = f2y.MedicareFTS(t).init(f"{input_dir}/{transfer_file}")

        columns = [col.column for col in fts.columns]
        column_type = [col.type for col in fts.columns]
        column_width = [col.width for col in fts.columns]
        column_long = [col.label for col in fts.columns]
        num_real_cols = int(fts.metadata["Columns in File"])

        underlying = base
        is_medpar = "medpar" in transfer_file.lower()
        if is_medpar:
            underlying = medpar

        num_people = len(underlying)
        columns = columns[0:num_real_cols]
        column_type = column_type[0:num_real_cols]
        column_width = column_width[0:num_real_cols]
        column_long = column_long[0:num_real_cols]
        print(num_people)
        print(underlying.index)

        data = pd.DataFrame(columns=columns)
        data[columns[0]] = range(num_people)
        data["actual_bene_id"] = underlying["actual_id"]

        formater: list[str] = []
        for i, column_name in enumerate(columns):
            col_type = column_type[i]
            col_width = column_width[i]
            col_long = column_long[i]
            if is_medpar:
                print(column_name)

            continue_next = False
            for pdf in prev_dataframes:
                if column_name in pdf.columns:
                    if column_name in ("BENE_ZIP", "BENE_ID"):
                        break
                    elif (
                        col_type == "NUM"
                        or "Number" in col_long
                        or "Year" in col_long
                    ):
                        formater.append(f"%0{int(col_width)}d")
                        continue_next = True
                        merged = data.merge(
                            pdf[["BENE_ID", column_name]],
                            left_on="actual_bene_id",
                            right_on="BENE_ID",
                            how="left",
                            suffixes=("_x", ""),
                        )
                        data[column_name] = merged[column_name]
                    elif col_type in ("CHAR", "DATE"):
                        data[column_name] = data[column_name].astype("string")
                        formater.append("%s")
                        continue_next = True
                        merged = data.merge(
                            pdf[["BENE_ID", column_name]],
                            left_on="actual_bene_id",
                            right_on="BENE_ID",
                            how="left",
                            suffixes=("_x", ""),
                        )
                        data[column_name] = merged[column_name]
                    break
            if continue_next:
                continue

            if (
                col_type == "NUM"
                or "Number" in col_long
                or "Year" in col_long
            ):
                values, fmt = number_generation(col_width, col_long, underlying, year)
                data[column_name] = values
                formater.append(fmt)

            elif col_type == "CHAR":
                values, fmt = char_generation(
                    column_name, col_width, col_long, underlying, is_medpar
                )
                data[column_name] = values
                formater.append(fmt)
                data[column_name] = data[column_name].astype("string")
                data[column_name] = data[column_name].str.rjust(int(col_width), " ")

            elif col_type == "DATE":
                values, fmt = date_generation(
                    col_width, col_long, underlying, is_medpar, start_date, end_date
                )
                data[column_name] = values
                data[column_name] = data[column_name].astype("string")
                data[column_name] = data[column_name].str.rjust(int(col_width), " ")
                formater.append(fmt)

            else:
                print("COLUMN TYPE NOT DETECTED")
                print(f"{col_type}")

        prev_dataframes.append(data)
        dat_file = transfer_file.replace(".fts", ".dat")
        print(formater)
        data = data.drop("actual_bene_id", errors="ignore", axis=1)
        np.savetxt(
            f"{output_dir}/{dat_file}",
            data.values,
            fmt=formater,
            delimiter="",
            newline="\r\n",
        )
