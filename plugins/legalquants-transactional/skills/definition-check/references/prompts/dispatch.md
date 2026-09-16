Perform one {stage} definition-check review packet.

Read:
{packet_path}

Follow the packet instruction literally. Process every packet item exactly once, preserve its numeric ordinal, and do not add prose. The response file is already prefilled from the packet's exact response_template. Edit that file in place, replace every null decision, preserve its keys and row order, and do not recreate its structure:
{response_path}

You own only that response file. Do not alter or clean any other file. Report the row count after writing.

Before reporting completion, run this validator:
{validation_command}

If validation fails, correct only the response file and run the validator once more. If the second validation fails, stop and report the exact validator error. Do not make a third attempt.
