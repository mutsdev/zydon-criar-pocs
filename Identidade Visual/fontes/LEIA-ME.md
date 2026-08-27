# Tipografia

`Inter.ttf` é a fonte variável Inter (SIL Open Font License 1.1), baixada de
`google/fonts`. Um arquivo só, com todos os pesos — `Regular`, `Medium`,
`SemiBold`, `Bold` — aplicados por `set_variation_by_name`.

Ela é **commitada de propósito**, em vez de usar fonte do sistema: Windows e
Linux não têm o mesmo conjunto, e fonte ausente na hora de compor é banner
quebrado sem aviso. `compor.fonte()` levanta se este arquivo sumir.
