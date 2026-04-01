#[test]
fn test_take_damage_with_armor() {
    let mut entity = Entity::new();
    entity.take_damage(30.0);
    assert_eq!(entity.health, 70.0);
}

#[test]
fn test_take_damage_exceeds_health() {
    let mut entity = Entity::new();
    entity.take_damage(200.0);
    assert_eq!(entity.health, -100.0);
}

#[test]
fn test_heal_after_damage() {
    let mut entity = Entity::new();
    entity.take_damage(30.0);
    entity.heal(20.0);
    assert_eq!(entity.health, 90.0);
}

#[test]
fn test_heal_over_max_health() {
    let mut entity = Entity::new();
    entity.heal(100.0);
    assert_eq!(entity.health, 150.0);
}