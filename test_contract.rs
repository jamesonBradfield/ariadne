#[test]
fn test_take_damage_with_armor() {
    let mut entity = Entity::new();
    entity.take_damage(100.0);
    assert_eq!(entity.health, 50.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_take_damage_exceeds_health() {
    let mut entity = Entity::new();
    entity.take_damage(200.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}

#[test]
fn test_heal_after_death() {
    let mut entity = Entity::new();
    entity.take_damage(200.0);
    entity.heal(50.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}

#[test]
fn test_take_damage_no_armor() {
    let mut entity = Entity::new();
    entity.armor = 0.0;
    entity.take_damage(100.0);
    assert_eq!(entity.health, 0.0);
    assert!(entity.is_dead);
}